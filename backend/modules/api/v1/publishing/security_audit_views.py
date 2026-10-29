"""Tenant-scoped read-only security-audit endpoint. No credential exposure."""
import logging
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.security_audit import security_snapshot, SecurityAuditError

logger = logging.getLogger(__name__)


class SecurityAuditThrottle(UserRateThrottle):
    scope = 'security_audit'
    rate = '6/min'


class SecurityAuditQuery(serializers.Serializer):
    limit = serializers.IntegerField(min_value=1, max_value=100, default=50)


class PublishingSecurityAuditAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [SecurityAuditThrottle]

    def get(self, request, pipeline_id):
        pipeline = resolve_pipeline(request.user, pipeline_id)
        query = SecurityAuditQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            data = security_snapshot(pipeline_id=pipeline.pk,
                                     limit=query.validated_data['limit'])
        except SecurityAuditError:
            response = Response({'success': False,
                                 'message': 'Không kiểm tra được Pipeline.'}, status=400)
        except Exception:
            logger.error('Security audit failed for pipeline_id=%s', pipeline.pk)
            response = Response({'success': False,
                                 'message': 'Kiểm toán bảo mật tạm thời không khả dụng.'}, status=503)
        else:
            response = Response({'success': True, 'data': data})
        response['Cache-Control'] = 'private, no-store'
        return response
