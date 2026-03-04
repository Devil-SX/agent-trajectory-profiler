import type { components, operations } from './api.generated';

type QueryOf<O extends keyof operations> = NonNullable<operations[O]['parameters']['query']>;

export type SessionSummary = components['schemas']['SessionSummary'];
export type SessionListResponse = components['schemas']['SessionListResponse'];
export type SessionDetailResponse = components['schemas']['SessionDetailResponse'];
export type SessionStatisticsResponse = components['schemas']['SessionStatisticsResponse'];

export type FrontendPreferences = components['schemas']['FrontendPreferences'];
export type FrontendPreferencesUpdate = components['schemas']['FrontendPreferencesUpdate'];

export type SyncRunDetail = components['schemas']['SyncRunDetail'];
export type SyncStatusResponse = components['schemas']['SyncStatusResponse'];

export type CapabilityListResponse = components['schemas']['CapabilityListResponse'];

export type AnalyticsOverviewResponse = components['schemas']['AnalyticsOverviewResponse'];
export type AnalyticsDistributionResponse = components['schemas']['AnalyticsDistributionResponse'];
export type AnalyticsTimeseriesResponse = components['schemas']['AnalyticsTimeseriesResponse'];
export type ProjectComparisonResponse = components['schemas']['ProjectComparisonResponse'];
export type ProjectSwimlaneResponse = components['schemas']['ProjectSwimlaneResponse'];

export type AnalyticsDimension = NonNullable<
  QueryOf<'get_analytics_distributions_api_analytics_distributions_get'>['dimension']
>;

export type AnalyticsInterval = NonNullable<
  QueryOf<'get_analytics_timeseries_api_analytics_timeseries_get'>['interval']
>;
