"""Small interface around the storage of uploaded documents (R3.6).

Files are stored exactly as uploaded, never parsed (R12.9); the database only holds the object
path. Locally the storage is a folder; in GCP it is the private Cloud Storage bucket of the
environment.
"""

import logging
import uuid
from pathlib import Path
from typing import Optional, Protocol

from google.api_core.exceptions import NotFound
from google.cloud import storage

logger = logging.getLogger(__name__)


class FileStorage(Protocol):
    """What the application asks of the document storage."""

    def save(self, object_path: str, content: bytes) -> None:
        """Store a file under an object path."""
        ...

    def read(self, object_path: str) -> Optional[bytes]:
        """Give the content of a stored file, or None when there is no such file."""
        ...

    def delete(self, object_path: str) -> None:
        """Remove a stored file; a file that is already gone is not an error."""
        ...


class LocalFileStorage:
    """A document storage in a local folder, for tests and local work."""

    def __init__(self, folder: Path) -> None:
        """Set the folder that holds the files."""
        self.folder = folder

    def find_file(self, object_path: str) -> Path:
        """Give the file of an object path, refusing a path that leaves the folder."""
        folder = self.folder.resolve()
        file_path = (folder / object_path).resolve()
        if not file_path.is_relative_to(folder):
            raise ValueError('The object path leaves the storage folder.')
        return file_path

    def save(self, object_path: str, content: bytes) -> None:
        """Write a file into the folder, creating its sub-folders."""
        file_path = self.find_file(object_path=object_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)
        logger.info(f'Stored file {object_path}.')

    def read(self, object_path: str) -> Optional[bytes]:
        """Read a file from the folder, or give None when it is not there."""
        file_path = self.find_file(object_path=object_path)
        if not file_path.is_file():
            logger.warning(f'Stored file {object_path} not found.')
            return None
        return file_path.read_bytes()

    def delete(self, object_path: str) -> None:
        """Remove a file from the folder."""
        file_path = self.find_file(object_path=object_path)
        file_path.unlink(missing_ok=True)
        logger.info(f'Removed stored file {object_path}.')


class BucketFileStorage:
    """A document storage in a Cloud Storage bucket, for the environments in GCP (R3.6).

    The bucket is private: files are only read through the application, with the service
    account of the Cloud Run service.
    """

    def __init__(self, bucket: storage.Bucket) -> None:
        """Set the bucket that holds the files."""
        self.bucket = bucket

    def save(self, object_path: str, content: bytes) -> None:
        """Write a file into the bucket, unmodified."""
        blob = self.bucket.blob(blob_name=object_path)
        blob.upload_from_string(data=content, content_type='application/octet-stream')
        logger.info(f'Stored file {object_path}.')

    def read(self, object_path: str) -> Optional[bytes]:
        """Read a file from the bucket, or give None when it is not there."""
        blob = self.bucket.blob(blob_name=object_path)
        try:
            return blob.download_as_bytes()
        except NotFound:
            logger.warning(f'Stored file {object_path} not found.')
            return None

    def delete(self, object_path: str) -> None:
        """Remove a file from the bucket."""
        blob = self.bucket.blob(blob_name=object_path)
        try:
            blob.delete()
        except NotFound:
            logger.info(f'Stored file {object_path} was already gone.')
            return
        logger.info(f'Removed stored file {object_path}.')


def build_object_path(worker_id: int, filename: str) -> str:
    """Build a new, unique object path for a document of a worker.

    Only the extension of the uploaded name is kept; the name itself stays in the database.
    """
    suffix = Path(filename).suffix.lower()
    return f'workers/{worker_id}/{uuid.uuid4().hex}{suffix}'


def build_file_storage(storage_bucket: Optional[str], storage_folder: str) -> FileStorage:
    """Give the document storage of this environment: the bucket when one is named (R3.6).

    In GCP the client signs in as the service account of the Cloud Run service; no key is
    configured anywhere (R2.7).
    """
    if not storage_bucket:
        return LocalFileStorage(folder=Path(storage_folder))
    client = storage.Client()
    bucket = client.bucket(bucket_name=storage_bucket)
    return BucketFileStorage(bucket=bucket)
