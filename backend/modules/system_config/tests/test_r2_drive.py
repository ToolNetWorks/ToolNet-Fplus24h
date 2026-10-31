import hashlib
import io
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from modules.albums.models import Album, AlbumImage
from modules.pipelines.models import Pipeline
from modules.system_config.services import r2_drive as drive


class R2DriveTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser('drive-admin', 'drive@example.test', 'test-password')
        cls.ctv = User.objects.create_user('hiu9h')
        cls.other_ctv = User.objects.create_user('CTV-2')
        cls.pipeline = Pipeline.objects.create(name='Hiu9h Pipeline', ctv=cls.ctv)
        cls.other_pipeline = Pipeline.objects.create(name='Other Pipeline', ctv=cls.other_ctv)
        cls.album = Album.objects.create(pipeline=cls.pipeline, name='Bộ sưu tập hiu9h')
        cls.other_album = Album.objects.create(pipeline=cls.other_pipeline, name='Other Album')
        out = io.BytesIO()
        Image.new('RGB', (800, 500), 'blue').save(out, format='WEBP')
        cls.content = out.getvalue()
        cls.image = cls.make_image(cls.album, 'hình gốc.jpg')
        cls.other_image = cls.make_image(cls.other_album, 'other.jpg')

    @classmethod
    def make_image(cls, album, filename, **values):
        obj = AlbumImage(album=album, original_filename=filename, mime_type='image/webp', file_size=len(cls.content), width=800, height=500, sha256=hashlib.sha256(cls.content).hexdigest(), upload_status='ready', **values)
        obj.storage_key = f'pipeline-albums/{album.pipeline_id}/{album.pk}/{obj.pk}.webp'
        obj.save()
        return obj

    def setUp(self):
        self.client.force_login(self.admin)
        self.root = reverse('r2-drive-root')
        self.album_url = reverse('r2-drive-album', kwargs={'pipeline_id': self.pipeline.pk, 'album_id': self.album.pk})
        self.image_args = {'pipeline_id': self.pipeline.pk, 'album_id': self.album.pk, 'image_id': self.image.pk}
        self.image_url = reverse('r2-drive-image-content', kwargs=self.image_args)
        self.metadata_url = reverse('r2-drive-image-metadata', kwargs=self.image_args)

    def mock_storage(self):
        client = MagicMock()
        client.get_object.side_effect = lambda **kwargs: {'Body': io.BytesIO(self.content), 'ContentLength': len(self.content)}
        return client

    def test_root_folders_are_real_ctv_and_pipeline_relations(self):
        with patch.object(drive, 'get_r2_client') as storage:
            result = self.client.get(self.root).json()
        folders = {item['name']: item for item in result['items']}
        self.assertEqual(set(folders), {'hiu9h', 'CTV-2'})
        self.assertEqual(folders['hiu9h']['pipeline_id'], str(self.pipeline.pk))
        self.assertEqual(folders['hiu9h']['image_count'], 1)
        self.assertEqual(folders['hiu9h']['album_count'], 1)
        storage.assert_not_called()

    def test_pipeline_album_and_images_do_not_mix_ctvs(self):
        pipeline_url = reverse('r2-drive-pipeline', kwargs={'pipeline_id': self.pipeline.pk})
        albums = self.client.get(pipeline_url).json()
        self.assertEqual([item['id'] for item in albums['items']], [str(self.album.pk)])
        response = self.client.get(self.album_url)
        self.assertEqual(response.status_code, 200)
        images = response.json()['items']
        self.assertEqual([item['name'] for item in images], ['hình gốc.jpg'])
        self.assertIn('/admin/config/r2-drive/', images[0]['thumbnail_url'])
        self.assertNotIn('storage_key', images[0])
        self.assertNotIn('bucket', images[0])
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_metadata_checks_all_three_ids(self):
        bad_args = {**self.image_args, 'image_id': self.other_image.pk}
        for name in ['r2-drive-image-content', 'r2-drive-image-metadata']:
            self.assertEqual(self.client.get(reverse(name, kwargs=bad_args)).status_code, 404)
        mismatch_album = reverse('r2-drive-album', kwargs={'pipeline_id': self.pipeline.pk, 'album_id': self.other_album.pk})
        self.assertEqual(self.client.get(mismatch_album).status_code, 404)
        value = self.client.get(self.metadata_url).json()
        self.assertEqual(value['width'], 800)
        self.assertEqual(value['file_size'], len(self.content))
        self.assertEqual(value['name'], self.image.original_filename)

    def test_search_across_ctv_album_filename_and_scoped_search(self):
        for search, kind in [('Hiu9h Pipeline', 'pipeline'), ('Bộ sưu tập', 'album'), ('hình gốc', 'image')]:
            result = self.client.get(self.root, {'q': search}).json()
            self.assertEqual(result['items'][0]['kind'], kind)
        self.assertEqual(self.client.get(self.album_url, {'q': 'other.jpg'}).json()['pagination']['total'], 0)
        url = reverse('r2-drive-pipeline', kwargs={'pipeline_id': self.pipeline.pk})
        self.assertEqual(self.client.get(url, {'q': 'other.jpg'}).json()['items'], [])

    def test_pagination_is_bounded_and_stable(self):
        for i in range(30):
            self.make_image(self.album, f'photo-{i:02}.jpg')
        first = self.client.get(self.album_url, {'page_size': 24}).json()
        second = self.client.get(self.album_url, {'page_size': 24, 'page': 2}).json()
        self.assertEqual(len(first['items']), 24)
        self.assertEqual(len(second['items']), 7)
        self.assertEqual(first['pagination']['total'], 31)
        self.assertTrue(first['pagination']['has_next'])
        self.assertFalse(second['pagination']['has_next'])
        self.assertFalse({i['id'] for i in first['items']} & {i['id'] for i in second['items']})
        for params in [{'page': 0}, {'page_size': 1000}, {'page': 9}, {'q': 'x' * 151}]:
            self.assertEqual(self.client.get(self.album_url, params).status_code, 400)

    def test_all_endpoints_require_active_superadmin(self):
        urls = [self.root, reverse('r2-drive-pipeline', kwargs={'pipeline_id': self.pipeline.pk}), self.album_url, self.image_url, self.metadata_url, reverse('r2-drive-prefixes'), reverse('r2-drive-object-content'), reverse('r2-drive-object-metadata')]
        User = get_user_model()
        users = [None, self.ctv, User.objects.create_user('staff', is_staff=True), User.objects.create_user('super-only', is_superuser=True), User.objects.create_user('inactive-admin', is_staff=True, is_superuser=True, is_active=False)]
        for user in users:
            self.client.logout()
            if user:
                self.client.force_login(user)
            for url in urls:
                with patch.object(drive, 'get_r2_client') as storage:
                    self.assertEqual(self.client.get(url).status_code, 403, (user, url))
                    storage.assert_not_called()

    def test_drive_endpoints_are_read_only(self):
        for url in [self.root, reverse('r2-drive-pipeline', kwargs={'pipeline_id': self.pipeline.pk}), self.album_url, self.image_url, self.metadata_url, reverse('r2-drive-prefixes'), reverse('r2-drive-object-content'), reverse('r2-drive-object-metadata')]:
            for method in ['post', 'put', 'patch', 'delete']:
                self.assertEqual(getattr(self.client, method)(url).status_code, 405)
        self.assertEqual(AlbumImage.objects.count(), 2)

    def test_preview_thumbnail_and_download_use_private_proxy(self):
        client = self.mock_storage()
        with patch.object(drive, 'get_r2_client', return_value=(client, 'private-bucket')):
            preview = self.client.get(self.image_url)
            thumb = self.client.get(self.image_url, {'thumbnail': 'true'})
            download = self.client.get(self.image_url, {'download': 'true'})
        self.assertEqual(preview.content, self.content)
        self.assertEqual(preview['Content-Type'], 'image/webp')
        self.assertEqual(preview['X-Content-Type-Options'], 'nosniff')
        self.assertIn('attachment;', download['Content-Disposition'])
        self.assertIn('.webp', download['Content-Disposition'])
        with Image.open(io.BytesIO(thumb.content)) as small:
            self.assertLessEqual(small.width, 360)
            self.assertLessEqual(small.height, 280)
        self.assertTrue(all(call.kwargs['Key'] == self.image.storage_key for call in client.get_object.call_args_list))
        for write in ['put_object', 'delete_object', 'copy_object', 'create_multipart_upload']:
            getattr(client, write).assert_not_called()

    def test_wrong_storage_key_rejected_before_r2_read(self):
        # Use a different UUID under the same album to check exact image identity.
        AlbumImage.objects.filter(pk=self.image.pk).update(storage_key=f'pipeline-albums/{self.pipeline.pk}/{self.album.pk}/{self.other_image.pk}.webp')
        with patch.object(drive, 'get_r2_client') as storage:
            self.assertEqual(self.client.get(self.image_url).status_code, 400)
            storage.assert_not_called()

    def test_integrity_error_is_safe_and_not_logged_with_secrets(self):
        client = self.mock_storage()
        self.image.sha256 = '0' * 64
        self.image.save(update_fields=['sha256'])
        with patch.object(drive, 'get_r2_client', return_value=(client, 'bucket')):
            self.assertEqual(self.client.get(self.image_url).status_code, 502)
        with patch.object(drive, 'get_r2_client', side_effect=RuntimeError('api-key-secret-cookie-private-url')):
            response = self.client.get(self.image_url)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('api-key-secret-cookie-private-url', response.content.decode())

    def test_raw_keys_prefixes_and_tampered_references_denied(self):
        with patch.object(drive, 'get_r2_client') as storage:
            for url in [self.root, self.image_url, reverse('r2-drive-prefixes'), reverse('r2-drive-object-content')]:
                for name in ['storage_key', 'prefix', 'bucket', 'key', 'url']:
                    self.assertEqual(self.client.get(url, {name: 'outside/secrets.webp'}).status_code, 400)
            for ref in ['outside/image.webp', 'invalid-signature', drive.token('prefix', prefix='folder/')]:
                self.assertEqual(self.client.get(reverse('r2-drive-object-content'), {'ref': ref}).status_code, 400)
            storage.assert_not_called()

    def test_prefix_browsing_uses_delimiter_bounded_pages_and_signed_cursor(self):
        client = MagicMock()
        client.list_objects_v2.return_value = {
            'CommonPrefixes': [{'Prefix': 'other-images/'}],
            'Contents': [{'Key': 'cover.jpg', 'Size': len(self.content), 'LastModified': datetime.now(timezone.utc)}],
            'IsTruncated': True, 'NextContinuationToken': 'r2-server-cursor',
        }
        url = reverse('r2-drive-prefixes')
        with patch.object(drive, 'get_r2_client', return_value=(client, 'private-bucket')):
            first = self.client.get(url).json()
            client.list_objects_v2.assert_called_with(Bucket='private-bucket', Prefix='', Delimiter='/', MaxKeys=24)
            folder = first['items'][0]
            self.assertEqual(folder['kind'], 'prefix')
            self.assertEqual(folder['name'], 'other-images')
            # The server cursor cannot be reused for a different folder.
            self.assertEqual(self.client.get(url, {'ref': folder['id'], 'cursor': first['next_cursor']}).status_code, 400)
            second = self.client.get(url, {'cursor': first['next_cursor']})
            self.assertEqual(second.status_code, 200)
            self.assertEqual(client.list_objects_v2.call_args.kwargs['ContinuationToken'], 'r2-server-cursor')
            client.list_objects_v2.return_value = {'CommonPrefixes': [], 'Contents': [], 'IsTruncated': False}
            child = self.client.get(url, {'ref': folder['id']}).json()
            self.assertEqual(child['breadcrumbs'][0]['name'], 'other-images')
            self.assertEqual(client.list_objects_v2.call_args.kwargs['Prefix'], 'other-images/')
        self.assertNotIn('private-bucket', str(first))

    def test_prefix_object_read_requires_server_issued_image_reference(self):
        client = self.mock_storage()
        url = reverse('r2-drive-object-content')
        ref = drive.token('object', key='other-images/private.webp')
        with patch.object(drive, 'get_r2_client', return_value=(client, 'bucket')):
            response = self.client.get(url, {'ref': ref, 'download': 'true'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, self.content)
            client.get_object.assert_called_once_with(Bucket='bucket', Key='other-images/private.webp')
            for key in ['../secret.webp', '/root.webp', 'a/../../secret.webp', 'a\\secret.webp', 'secrets.env', 'script.svg']:
                self.assertEqual(self.client.get(url, {'ref': drive.token('object', key=key)}).status_code, 400)
        with patch.object(drive, 'TOKEN_TTL', -1):
            self.assertEqual(self.client.get(url, {'ref': ref}).status_code, 400)

    def test_prefix_metadata_includes_dimensions_without_credentials(self):
        client = self.mock_storage()
        client.head_object.return_value = {'ContentLength': len(self.content), 'LastModified': datetime.now(timezone.utc), 'Metadata': {'secret': 'must-not-expose'}}
        ref = drive.token('object', key='other/photo.webp')
        with patch.object(drive, 'get_r2_client', return_value=(client, 'hidden-bucket')):
            response = self.client.get(reverse('r2-drive-object-metadata'), {'ref': ref})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['width'], 800)
        self.assertEqual(response.json()['height'], 500)
        self.assertNotIn('must-not-expose', response.content.decode())
        self.assertNotIn('hidden-bucket', response.content.decode())

    def test_known_image_in_raw_prefix_uses_original_filename_and_database_scope(self):
        client = MagicMock()
        client.list_objects_v2.return_value = {'Contents': [{'Key': self.image.storage_key, 'Size': len(self.content), 'LastModified': datetime.now(timezone.utc)}]}
        ref = drive.token('prefix', prefix=f'pipeline-albums/{self.pipeline.pk}/{self.album.pk}/')
        with patch.object(drive, 'get_r2_client', return_value=(client, 'bucket')):
            response = self.client.get(reverse('r2-drive-prefixes'), {'ref': ref})
        entry = response.json()['items'][0]
        self.assertEqual(entry['name'], 'hình gốc.jpg')
        self.assertEqual(entry['kind'], 'image')
        self.assertIn(f'/pipelines/{self.pipeline.pk}/albums/{self.album.pk}/', entry['preview_url'])

    def test_pending_image_and_oversized_content_are_not_served(self):
        AlbumImage.objects.filter(pk=self.image.pk).update(upload_status='pending')
        with patch.object(drive, 'get_r2_client') as storage:
            self.assertEqual(self.client.get(self.image_url).status_code, 404)
            storage.assert_not_called()
        client = MagicMock()
        body = MagicMock()
        client.get_object.return_value = {'ContentLength': drive.MAX_OUTPUT_BYTES + 1, 'Body': body}
        with patch.object(drive, 'get_r2_client', return_value=(client, 'bucket')):
            response = self.client.get(reverse('r2-drive-object-content'), {'ref': drive.token('object', key='large.webp')})
        self.assertEqual(response.status_code, 400)
        body.read.assert_not_called()
        body.close.assert_called_once()

    def test_database_outage_is_a_safe_error(self):
        from django.db import OperationalError
        with patch.object(drive, 'browse_database', side_effect=OperationalError('password=private-neon-secret')):
            response = self.client.get(self.root)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private-neon-secret', response.content.decode())
