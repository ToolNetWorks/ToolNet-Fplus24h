"""Read-only CTV reporting API. No scheduler/job mutations or external requests."""
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from modules.api.v1.albums.views import resolve_pipeline
from modules.publishing.services.reports import (
    report_summary, report_batches, report_batch_detail, report_groups,
    report_accounts,
)


class ReportReadThrottle(UserRateThrottle):
    rate = '60/min'


class ReportFilters(serializers.Serializer):
    days = serializers.ChoiceField(choices=(7, 30, 90), default=30)
    schedule_id = serializers.UUIDField(required=False)
    page = serializers.IntegerField(min_value=1, max_value=100000, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=50, default=20)
    search = serializers.CharField(required=False, allow_blank=True, max_length=100,
                                   trim_whitespace=True)

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError('Bộ lọc báo cáo không hợp lệ.')
        return attrs


def response(data):
    result = Response({'success': True, 'data': data})
    result['Cache-Control'] = 'private, no-store'
    return result


class BaseReportAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ReportReadThrottle]

    def filters(self, request):
        params = ReportFilters(data=request.query_params)
        params.is_valid(raise_exception=True)
        return params.validated_data

    def pipeline(self, request, pipeline_id):
        return resolve_pipeline(request.user, pipeline_id)


class PipelineReportSummaryAPIView(BaseReportAPIView):
    def get(self, request, pipeline_id):
        pipeline = self.pipeline(request, pipeline_id)
        val = self.filters(request)
        return response(report_summary(pipeline_id=pipeline.pk, days=int(val['days']),
                                       schedule_id=val.get('schedule_id')))


class PipelineReportBatchesAPIView(BaseReportAPIView):
    def get(self, request, pipeline_id):
        pipeline = self.pipeline(request, pipeline_id)
        val = self.filters(request)
        return response(report_batches(pipeline_id=pipeline.pk, days=int(val['days']),
                                       schedule_id=val.get('schedule_id'),
                                       page=val['page'], page_size=val['page_size']))


class PipelineReportBatchDetailAPIView(BaseReportAPIView):
    def get(self, request, pipeline_id, batch_id):
        pipeline = self.pipeline(request, pipeline_id)
        return response(report_batch_detail(pipeline_id=pipeline.pk, batch_id=batch_id))


class PipelineReportGroupsAPIView(BaseReportAPIView):
    def get(self, request, pipeline_id):
        pipeline = self.pipeline(request, pipeline_id)
        val = self.filters(request)
        return response(report_groups(pipeline_id=pipeline.pk, days=int(val['days']),
                                      schedule_id=val.get('schedule_id'),
                                      search=val.get('search', ''),
                                      page=val['page'], page_size=val['page_size']))


class PipelineReportAccountsAPIView(BaseReportAPIView):
    def get(self, request, pipeline_id):
        pipeline = self.pipeline(request, pipeline_id)
        val = self.filters(request)
        return response(report_accounts(pipeline_id=pipeline.pk, days=int(val['days']),
                                        schedule_id=val.get('schedule_id'),
                                        search=val.get('search', ''),
                                        page=val['page'], page_size=val['page_size']))
