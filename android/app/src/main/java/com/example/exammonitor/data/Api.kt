package com.example.exammonitor.data

import com.example.exammonitor.core.*
import com.google.gson.JsonObject
import retrofit2.Response
import retrofit2.http.*

/** Only endpoints that already exist in the backend (Phases 1-6). Paths are relative to the configured base URL. */
interface ExamApi {
    // ---- Phase 11 cross-module workflow aggregation
    @GET("api/integration/overview") suspend fun integrationOverview(): Response<JsonObject>
    @GET("api/integration/exams/{id}/readiness") suspend fun examWorkflowReadiness(@Path("id") id: Int): Response<JsonObject>
    @GET("api/analytics/me") suspend fun myAnalytics(): Response<JsonObject>
    // ---- authentication
    @POST("api/auth/login") suspend fun login(@Body body: LoginRequest): Response<LoginResponseDto>
    @GET("api/auth/profile") suspend fun profile(): Response<ProfileDto>
    @GET("api/auth/profile") suspend fun profileWithToken(@Header("Authorization") bearer: String): Response<ProfileDto>
    @POST("api/auth/logout") suspend fun logout(): Response<DetailDto>
    @POST("api/auth/change-password") suspend fun changePassword(@Body body: ChangePasswordRequest): Response<ChangePasswordResponseDto>
    @POST("api/auth/forgot-password") suspend fun forgotPassword(@Body body: ForgotRequest): Response<DetailDto>
    @POST("api/auth/reset-password") suspend fun resetPassword(@Body body: ResetRequest): Response<DetailDto>

    // ---- student (always called with the signed-in student's OWN register number)
    @GET("api/lookup/{reg}") suspend fun lookup(@Path("reg") registerNumber: String): Response<LookupDto>
    @GET("api/results/{reg}") suspend fun results(@Path("reg") registerNumber: String): Response<List<ResultDto>>

    // ---- shared
    @GET("api/exams") suspend fun publishedExams(): Response<List<ExamDto>>
    @GET("api/announcements") suspend fun announcements(): Response<List<AnnouncementDto>>

    // ---- notifications (Phase 6)
    @GET("api/notifications") suspend fun notifications(@Query("status") status: String, @Query("limit") limit: Int,
                                                         @Query("offset") offset: Int): Response<List<NotificationDto>>
    @GET("api/notifications/unread-count") suspend fun unreadCount(): Response<UnreadDto>
    @POST("api/notifications/read-all") suspend fun readAll(): Response<ReadAllDto>
    @GET("api/notifications/preferences") suspend fun preferences(): Response<PreferencesDto>
    @PUT("api/notifications/preferences") suspend fun updatePreferences(@Body body: PreferencesUpdateRequest): Response<PreferencesDto>
    @GET("api/notifications/{id}") suspend fun notification(@Path("id") id: Int): Response<NotificationDto>
    @POST("api/notifications/{id}/read") suspend fun markRead(@Path("id") id: Int): Response<NotificationDto>
    @POST("api/notifications/{id}/unread") suspend fun markUnread(@Path("id") id: Int): Response<NotificationDto>
    @POST("api/notifications/{id}/archive") suspend fun archive(@Path("id") id: Int): Response<NotificationDto>

    // ---- staff / administrators / invigilators (role enforced by the backend)
    @GET("api/dashboard") suspend fun dashboard(): Response<DashboardDto>
    @GET("api/admin/exams") suspend fun adminExams(@Query("q") q: String, @Query("status") status: String,
                                                    @Query("limit") limit: Int, @Query("offset") offset: Int): Response<List<ExamDto>>
    @GET("api/admin/reports/exams/{id}/summary") suspend fun examSummary(@Path("id") id: Int): Response<ExamSummaryDto>
    @GET("api/admin/reports/exams/{id}/halls") suspend fun examHalls(@Path("id") id: Int): Response<List<HallOccupancyDto>>
    @GET("api/allotments/exam/{id}") suspend fun examRoster(@Path("id") id: Int, @Query("q") q: String, @Query("limit") limit: Int,
                                                              @Query("offset") offset: Int): Response<List<RosterDto>>
    @GET("api/admin/reports/students/seats") suspend fun studentSeats(@Query("q") q: String): Response<List<StaffStudentDto>>
    @POST("api/exams/{id}/publish") suspend fun publishExam(@Path("id") id: Int): Response<ExamDto>
    @POST("api/exams/{id}/unpublish") suspend fun unpublishExam(@Path("id") id: Int): Response<ExamDto>
}
