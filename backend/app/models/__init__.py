"""Import every model so Base.metadata is complete (Alembic, create_all)."""

from app.models.artifact import Artifact
from app.models.audit import AuditLog
from app.models.comment import Comment
from app.models.data_source import DataSource
from app.models.issue import Issue
from app.models.job import Job
from app.models.project import Project, ProjectMember
from app.models.project_request import ProjectRequest
from app.models.resource_sample import ResourceSample
from app.models.setting import SystemSetting
from app.models.upload import Upload
from app.models.user import User

__all__ = [
    "Artifact",
    "AuditLog",
    "Comment",
    "DataSource",
    "Issue",
    "Job",
    "Project",
    "ProjectMember",
    "ProjectRequest",
    "ResourceSample",
    "SystemSetting",
    "Upload",
    "User",
]
