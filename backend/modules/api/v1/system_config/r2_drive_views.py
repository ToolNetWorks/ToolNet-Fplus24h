from pathlib import PurePosixPath

from django.db import DatabaseError

from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.api.v1.permissions import IsSuperAdmin
from modules.system_config.services import r2_drive as drive


class DriveQuery(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=48, default=24)
    q = serializers.CharField(required=False, allow_blank=True, max_length=150, default='')


class PrefixQuery(serializers.Serializer):
    page_size = serializers.IntegerField(min_value=1, max_value=48, default=24)
    ref = serializers.CharField(required=False, allow_blank=True, max_length=8192, default='')
    cursor = serializers.CharField(required=False, allow_blank=True, max_length=16384, default='')


class ContentQuery(serializers.Serializer):
    thumbnail = serializers.BooleanField(default=False)
    download = serializers.BooleanField(default=False)
    ref = serializers.CharField(required=False, max_length=8192)


def query(request, serializer_class):
    if {'storage_key', 'key', 'prefix', 'bucket', 'url'} & set(request.query_params):
        raise serializers.ValidationError('Không được chỉ định trực tiếp vị trí object R2.')
    serializer = serializer_class(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class ReadOnlyDriveAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsSuperAdmin]
    http_method_names = ['get', 'head', 'options']

    def handle_exception(self, exc):
        if isinstance(exc, DatabaseError):
            return Response({'detail': 'Không kết nối được database. Vui lòng thử lại sau.'}, status=503)
        return super().handle_exception(exc)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


class DriveRootAPIView(ReadOnlyDriveAPIView):
    def get(self, request):
        return Response(drive.browse_database(query(request, DriveQuery)))


class DrivePipelineAPIView(ReadOnlyDriveAPIView):
    def get(self, request, pipeline_id):
        pipeline = drive.pipeline_or_404(pipeline_id)
        return Response(drive.browse_database(query(request, DriveQuery), pipeline=pipeline))


class DriveAlbumAPIView(ReadOnlyDriveAPIView):
    def get(self, request, pipeline_id, album_id):
        pipeline = drive.pipeline_or_404(pipeline_id)
        album = drive.album_or_404(pipeline.pk, album_id)
        return Response(drive.browse_database(query(request, DriveQuery), pipeline=pipeline, album=album))


class DriveImageMetadataAPIView(ReadOnlyDriveAPIView):
    def get(self, request, pipeline_id, album_id, image_id):
        query(request, DriveQuery)
        return Response(drive.image_entry(drive.image_or_404(pipeline_id, album_id, image_id)))


class DriveImageContentAPIView(ReadOnlyDriveAPIView):
    def get(self, request, pipeline_id, album_id, image_id):
        params = query(request, ContentQuery)
        image = drive.image_or_404(pipeline_id, album_id, image_id)
        return drive.database_image_response(image, thumbnail=params['thumbnail'], download=params['download'])


class DrivePrefixesAPIView(ReadOnlyDriveAPIView):
    def get(self, request):
        return Response(drive.browse_prefixes(query(request, PrefixQuery)))


class DriveObjectContentAPIView(ReadOnlyDriveAPIView):
    def get(self, request):
        params = query(request, ContentQuery)
        key = drive.prefix_object_key(params.get('ref', ''))
        return drive.render_image(drive.read_object(key), PurePosixPath(key).name, thumbnail=params['thumbnail'], download=params['download'])


class DriveObjectMetadataAPIView(ReadOnlyDriveAPIView):
    def get(self, request):
        params = query(request, PrefixQuery)
        return Response(drive.prefix_metadata(params.get('ref', '')))
