"""Read-only R2 Drive. No method in this module writes to the bucket or database."""
import hashlib
import io
import logging
import warnings
from pathlib import PurePosixPath

from django.core import signing
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.utils.http import content_disposition_header
from PIL import Image, ImageOps
from rest_framework.exceptions import APIException, ValidationError

from modules.albums.models import Album, AlbumImage
from modules.albums.services.r2_storage import MAX_OUTPUT_BYTES, MAX_PIXELS, get_r2_client
from modules.pipelines.models import Pipeline

logger = logging.getLogger(__name__)
TOKEN_SALT = 'toolnet.r2-drive.readonly.v1'
TOKEN_TTL = 3600
IMAGE_EXTENSIONS = {'.webp', '.png', '.jpg', '.jpeg', '.gif', '.avif'}


class StorageUnavailable(APIException):
    status_code = 502
    default_detail = 'Không thể đọc R2. Vui lòng thử lại hoặc kiểm tra kết nối R2.'


def token(kind, **data):
    return signing.dumps({'kind': kind, **data}, salt=TOKEN_SALT, compress=True)


def untoken(value, kind):
    try:
        data = signing.loads(value, salt=TOKEN_SALT, max_age=TOKEN_TTL)
        if data.get('kind') != kind:
            raise ValueError()
        return data
    except (signing.BadSignature, ValueError, TypeError):
        raise ValidationError('Tham chiếu R2 không hợp lệ hoặc đã hết hạn. Hãy mở lại từ thư mục gốc.') from None


def pipeline_or_404(pipeline_id):
    from django.shortcuts import get_object_or_404
    return get_object_or_404(Pipeline.objects.select_related('ctv'), pk=pipeline_id)


def album_or_404(pipeline_id, album_id):
    from django.shortcuts import get_object_or_404
    return get_object_or_404(Album, pk=album_id, pipeline_id=pipeline_id)


def image_or_404(pipeline_id, album_id, image_id):
    from django.shortcuts import get_object_or_404
    return get_object_or_404(
        AlbumImage.objects.select_related('album__pipeline__ctv'),
        pk=image_id, album_id=album_id, album__pipeline_id=pipeline_id,
    )


def image_entry(image):
    album = image.album
    pipeline = album.pipeline
    base = f'/api/v1/admin/config/r2-drive/pipelines/{pipeline.pk}/albums/{album.pk}/images/{image.pk}'
    ready = image.upload_status == AlbumImage.UploadStatus.READY
    return {
        'kind': 'image', 'id': str(image.pk), 'name': image.original_filename,
        'pipeline_id': str(pipeline.pk), 'pipeline_name': pipeline.name,
        'ctv_name': pipeline.ctv.username, 'album_id': str(album.pk), 'album_name': album.name,
        'file_size': image.file_size, 'width': image.width, 'height': image.height,
        'mime_type': image.mime_type, 'created_at': image.created_at.isoformat(),
        'status': image.upload_status,
        'thumbnail_url': f'{base}/content/?thumbnail=true' if ready else None,
        'preview_url': f'{base}/content/' if ready else None,
        'download_url': f'{base}/content/?download=true' if ready else None,
        'metadata_url': f'{base}/',
    }


def album_entry(album):
    pipeline = album.pipeline
    return {
        'kind': 'album', 'id': str(album.pk), 'name': album.name,
        'pipeline_id': str(pipeline.pk), 'pipeline_name': pipeline.name,
        'ctv_name': pipeline.ctv.username, 'album_id': str(album.pk), 'album_name': album.name,
        'image_count': album.image_count, 'status': 'enabled' if album.is_enabled else 'disabled',
        'created_at': album.created_at.isoformat(),
    }


def pipeline_entry(pipeline):
    return {
        'kind': 'pipeline', 'id': str(pipeline.pk), 'name': pipeline.ctv.username,
        'pipeline_id': str(pipeline.pk), 'pipeline_name': pipeline.name,
        'ctv_name': pipeline.ctv.username, 'album_count': pipeline.album_count,
        'image_count': pipeline.image_count, 'status': pipeline.status,
        'created_at': pipeline.created_at.isoformat(),
    }


def browse_database(params, pipeline=None, album=None):
    """Page across a maximum of three querysets without materializing other pages."""
    q = params.get('q', '')
    groups = []
    if pipeline is None:
        pipelines = Pipeline.objects.select_related('ctv').annotate(
            album_count=Count('albums', distinct=True), image_count=Count('albums__images', distinct=True),
        ).order_by('ctv__username', 'pk')
        if q:
            pipelines = pipelines.filter(Q(ctv__username__icontains=q) | Q(name__icontains=q))
        groups.append((pipelines, pipeline_entry))
    if (pipeline is not None and album is None) or (pipeline is None and q):
        albums = Album.objects.select_related('pipeline__ctv').annotate(image_count=Count('images')).order_by('name', 'pk')
        if pipeline:
            albums = albums.filter(pipeline=pipeline)
        if q:
            albums = albums.filter(name__icontains=q)
        groups.append((albums, album_entry))
    if album is not None or q:
        images = AlbumImage.objects.select_related('album__pipeline__ctv').order_by('original_filename', 'pk')
        if album:
            images = images.filter(album=album)
        elif pipeline:
            images = images.filter(album__pipeline=pipeline)
        if q:
            images = images.filter(original_filename__icontains=q)
        groups.append((images, image_entry))
    page, size = params['page'], params['page_size']
    counted = [(qs, serialize, qs.count()) for qs, serialize in groups]
    total = sum(count for _, _, count in counted)
    pages = max(1, (total + size - 1) // size)
    if page > pages:
        raise ValidationError({'page': 'Trang không tồn tại.'})
    start, end, offset = (page - 1) * size, page * size, 0
    entries = []
    for qs, serialize, count in counted:
        low, high = max(0, start - offset), min(count, end - offset)
        if low < high:
            entries.extend(serialize(item) for item in qs[low:high])
        offset += count
    context = {'pipeline_id': str(pipeline.pk), 'pipeline_name': pipeline.name, 'ctv_name': pipeline.ctv.username} if pipeline else {}
    if album:
        context.update({'album_id': str(album.pk), 'album_name': album.name})
    return {
        'items': entries, 'context': context,
        'pagination': {'page': page, 'page_size': size, 'total': total, 'total_pages': pages, 'has_next': page < pages, 'has_previous': page > 1},
    }


def read_object(key):
    """Bounded read; caller has already resolved a DB image or verified a server-issued reference."""
    try:
        client, bucket = get_r2_client()
        result = client.get_object(Bucket=bucket, Key=key)
        body = result['Body']
        try:
            if result.get('ContentLength', 0) > MAX_OUTPUT_BYTES:
                raise ValidationError('Ảnh vượt quá giới hạn xem/tải 15 MB.')
            content = body.read(MAX_OUTPUT_BYTES + 1)
        finally:
            body.close()
        if len(content) > MAX_OUTPUT_BYTES:
            raise ValidationError('Ảnh vượt quá giới hạn xem/tải 15 MB.')
        return content
    except ValidationError:
        raise
    except Exception as exc:
        code = getattr(exc, 'response', {}).get('Error', {}).get('Code')
        if code in {'NoSuchKey', 'NotFound', '404'}:
            raise Http404('Ảnh không còn tồn tại trong R2.') from None
        # Never log SDK exceptions: they may contain signed URLs or credentials.
        logger.error('R2 Drive object read failed')
        raise StorageUnavailable() from None


def render_image(content, filename, *, thumbnail=False, download=False):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in {'JPEG', 'PNG', 'WEBP', 'GIF', 'AVIF'} or image.width * image.height > MAX_PIXELS:
                    raise ValueError()
                mime = Image.MIME.get(image.format, 'application/octet-stream')
                if thumbnail:
                    image = ImageOps.exif_transpose(image)
                    image.thumbnail((360, 280))
                    image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
                    output = io.BytesIO()
                    image.save(output, format='WEBP', quality=78)
                    content, mime = output.getvalue(), 'image/webp'
                else:
                    image.verify()
    except Exception:
        raise ValidationError('Nội dung ảnh không hợp lệ hoặc kích thước ảnh quá lớn.') from None
    response = HttpResponse(content, content_type=mime)
    response['Content-Disposition'] = content_disposition_header(download, filename)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


def database_image_response(image, *, thumbnail=False, download=False):
    if image.upload_status != AlbumImage.UploadStatus.READY:
        raise Http404('Ảnh chưa sẵn sàng.')
    expected_key = f'pipeline-albums/{image.album.pipeline_id}/{image.album_id}/{image.pk}.webp'
    if image.storage_key != expected_key or image.mime_type != 'image/webp' or not 0 < image.file_size <= MAX_OUTPUT_BYTES:
        raise ValidationError('Metadata ảnh không hợp lệ.')
    content = read_object(expected_key)
    if len(content) != image.file_size or hashlib.sha256(content).hexdigest() != image.sha256:
        raise StorageUnavailable('Dữ liệu ảnh không toàn vẹn.')
    filename = PurePosixPath(image.original_filename.replace('\\', '/')).stem + '.webp'
    return render_image(content, filename, thumbnail=thumbnail, download=download)


def _validate_path(value):
    # References are minted by the server; never accept a raw prefix/storage_key parameter.
    if not isinstance(value, str) or len(value) > 1024 or value.startswith('/') or '\\' in value or any(part in {'.', '..'} for part in value.split('/')) or any(ord(c) < 32 for c in value):
        raise ValidationError('Tham chiếu thư mục không hợp lệ.')
    return value


def browse_prefixes(params):
    ref = params.get('ref', '')
    prefix = _validate_path(untoken(ref, 'prefix')['prefix']) if ref else ''
    cursor = params.get('cursor', '')
    arguments = {'Prefix': prefix, 'Delimiter': '/', 'MaxKeys': params['page_size']}
    if cursor:
        data = untoken(cursor, 'cursor')
        if data.get('prefix') != prefix:
            raise ValidationError('Con trỏ phân trang không thuộc thư mục này.')
        arguments['ContinuationToken'] = data['cursor']
    try:
        client, bucket = get_r2_client()
        result = client.list_objects_v2(Bucket=bucket, **arguments)
    except Exception:
        logger.error('R2 Drive prefix listing failed')
        raise StorageUnavailable() from None
    items = []
    for folder in result.get('CommonPrefixes', []):
        child = _validate_path(folder['Prefix'])
        if not child.startswith(prefix) or child == prefix or not child.endswith('/'):
            continue
        items.append({'kind': 'prefix', 'id': token('prefix', prefix=child), 'name': child.rstrip('/').rsplit('/', 1)[-1]})
    keys = [obj['Key'] for obj in result.get('Contents', []) if not obj['Key'].endswith('/')]
    known_images = {
        image.storage_key: image
        for image in AlbumImage.objects.filter(storage_key__in=keys).select_related('album__pipeline__ctv')
    } if keys else {}
    for obj in result.get('Contents', []):
        key = _validate_path(obj['Key'])
        if key == prefix or key.endswith('/') or not key.startswith(prefix):
            continue
        if key in known_images:
            items.append(image_entry(known_images[key]))
            continue
        ref = token('object', key=key)
        base = '/api/v1/admin/config/r2-drive/objects'
        is_image = PurePosixPath(key).suffix.lower() in IMAGE_EXTENSIONS
        items.append({
            'kind': 'object', 'id': ref, 'name': key.rsplit('/', 1)[-1], 'file_size': obj['Size'],
            'created_at': obj['LastModified'].isoformat(), 'status': 'stored',
            'thumbnail_url': f'{base}/content/?ref={ref}&thumbnail=true' if is_image else None,
            'preview_url': f'{base}/content/?ref={ref}' if is_image else None,
            'download_url': f'{base}/content/?ref={ref}&download=true' if is_image else None,
            'metadata_url': f'{base}/metadata/?ref={ref}',
        })
    parts = prefix.rstrip('/').split('/') if prefix else []
    breadcrumbs = [{'name': part, 'ref': token('prefix', prefix='/'.join(parts[:i + 1]) + '/')} for i, part in enumerate(parts)]
    more = bool(result.get('IsTruncated'))
    return {
        'items': items, 'breadcrumbs': breadcrumbs,
        'next_cursor': token('cursor', prefix=prefix, cursor=result['NextContinuationToken']) if more else None,
        'pagination': {'page_size': params['page_size'], 'has_next': more},
    }


def prefix_object_key(ref):
    key = _validate_path(untoken(ref, 'object')['key'])
    if PurePosixPath(key).suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValidationError('Chỉ hỗ trợ xem và tải ảnh JPEG, PNG, WebP, GIF hoặc AVIF.')
    return key


def prefix_metadata(ref):
    key = _validate_path(untoken(ref, 'object')['key'])
    try:
        client, bucket = get_r2_client()
        metadata = client.head_object(Bucket=bucket, Key=key)
    except Exception:
        raise StorageUnavailable() from None
    dimensions = {'width': None, 'height': None}
    if PurePosixPath(key).suffix.lower() in IMAGE_EXTENSIONS and 0 < metadata['ContentLength'] <= MAX_OUTPUT_BYTES:
        content = read_object(key)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    if image.width * image.height > MAX_PIXELS:
                        raise ValueError()
                    dimensions = {'width': image.width, 'height': image.height}
        except Exception:
            raise ValidationError('Nội dung ảnh không hợp lệ.') from None
    return {'name': key.rsplit('/', 1)[-1], 'file_size': metadata['ContentLength'], 'created_at': metadata['LastModified'].isoformat(), 'status': 'stored', **dimensions}
