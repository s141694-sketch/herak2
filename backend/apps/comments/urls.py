from django.urls import path

from . import views

urlpatterns = [
    path("programs/<int:pk>/comments/", views.ProgramCommentsView.as_view(), name="program-comments"),
    path("comments/<int:pk>/", views.CommentDetailView.as_view(), name="comment-detail"),
    path("comments/<int:pk>/replies/", views.CommentRepliesView.as_view(), name="comment-replies"),
    path("comments/<int:pk>/resolve/", views.ResolveCommentView.as_view(), name="comment-resolve"),
    path("comments/<int:pk>/reopen/", views.ReopenCommentView.as_view(), name="comment-reopen"),
]
