"""File storage of uploaded documents: the local folder and the bucket (R3.6)."""

from pathlib import Path

import pytest
from google.api_core.exceptions import NotFound

from dimonapp import storage as storage_module
from dimonapp.settings import load_settings
from dimonapp.storage import (
    BucketFileStorage,
    LocalFileStorage,
    build_file_storage,
    build_object_path,
)

CONTENT = b'%PDF-1.4 fake \x00\xff bytes'


def test_r3_6_file_is_stored_unmodified(tmp_path: Path) -> None:
    """What is read back is byte for byte what was saved."""
    storage = LocalFileStorage(folder=tmp_path / 'storage')

    storage.save(object_path='workers/1/contract.pdf', content=CONTENT)

    assert storage.read(object_path='workers/1/contract.pdf') == CONTENT
    assert (tmp_path / 'storage' / 'workers' / '1' / 'contract.pdf').read_bytes() == CONTENT


def test_r3_6_missing_file_reads_as_none(tmp_path: Path) -> None:
    """A path without a file gives None instead of an error."""
    storage = LocalFileStorage(folder=tmp_path)

    assert storage.read(object_path='workers/1/unknown.pdf') is None


def test_r12_7_deleted_file_is_gone(tmp_path: Path) -> None:
    """A deleted file can no longer be read, and deleting it twice is not an error."""
    storage = LocalFileStorage(folder=tmp_path)
    storage.save(object_path='workers/1/contract.pdf', content=CONTENT)

    storage.delete(object_path='workers/1/contract.pdf')
    storage.delete(object_path='workers/1/contract.pdf')

    assert storage.read(object_path='workers/1/contract.pdf') is None


@pytest.mark.parametrize('object_path', ['../outside.pdf', '/etc/passwd', 'workers/../../x.pdf'])
def test_r3_6_path_outside_the_folder_is_refused(tmp_path: Path, object_path: str) -> None:
    """The storage never reads or writes outside its own folder."""
    storage = LocalFileStorage(folder=tmp_path / 'storage')

    with pytest.raises(ValueError):
        storage.save(object_path=object_path, content=CONTENT)
    with pytest.raises(ValueError):
        storage.read(object_path=object_path)


def test_r3_6_object_path_is_unique_and_keeps_only_the_extension() -> None:
    """Two uploads of the same name get different paths, without the name itself."""
    first_path = build_object_path(worker_id=7, filename='Contrat Lotte.PDF')
    second_path = build_object_path(worker_id=7, filename='Contrat Lotte.PDF')

    assert first_path != second_path
    assert first_path.startswith('workers/7/')
    assert first_path.endswith('.pdf')
    assert 'Lotte' not in first_path


def test_r3_6_storage_folder_comes_from_the_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Without a bucket, STORAGE_FOLDER names the local folder (R2.4)."""
    storage_folder = tmp_path / 'documents'
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://user:password@localhost/database')
    monkeypatch.setenv('STORAGE_FOLDER', str(storage_folder))
    settings = load_settings()

    storage = build_file_storage(
        storage_bucket=settings.storage_bucket,
        storage_folder=settings.storage_folder,
    )
    storage.save(object_path='a.pdf', content=CONTENT)

    assert (storage_folder / 'a.pdf').read_bytes() == CONTENT


class FakeBlob:
    """One object of a fake bucket; a missing object answers as Cloud Storage does."""

    def __init__(self, objects: dict[str, bytes], name: str) -> None:
        """Remember the objects of the bucket and the name of this one."""
        self.objects = objects
        self.name = name

    def upload_from_string(self, data: bytes, content_type: str) -> None:
        """Store the content."""
        self.objects[self.name] = data

    def download_as_bytes(self) -> bytes:
        """Give the content, or refuse as Cloud Storage does when there is none."""
        if self.name not in self.objects:
            raise NotFound('No such object.')
        return self.objects[self.name]

    def delete(self) -> None:
        """Remove the content, or refuse as Cloud Storage does when there is none."""
        if self.name not in self.objects:
            raise NotFound('No such object.')
        del self.objects[self.name]


class FakeBucket:
    """A bucket kept in memory, so no test calls Google."""

    def __init__(self) -> None:
        """Start empty."""
        self.objects: dict[str, bytes] = {}

    def blob(self, blob_name: str) -> FakeBlob:
        """Give the object with a name."""
        return FakeBlob(objects=self.objects, name=blob_name)


class FakeClient:
    """A Cloud Storage client that only remembers which bucket was asked for."""

    bucket_names: list[str] = []

    def bucket(self, bucket_name: str) -> FakeBucket:
        """Give a fake bucket and remember its name."""
        self.bucket_names.append(bucket_name)
        return FakeBucket()


def test_r3_6_bucket_stores_the_file_unmodified_under_its_object_path() -> None:
    """What is read back from the bucket is byte for byte what was saved."""
    bucket = FakeBucket()
    storage = BucketFileStorage(bucket=bucket)

    storage.save(object_path='workers/1/contract.pdf', content=CONTENT)

    assert bucket.objects == {'workers/1/contract.pdf': CONTENT}
    assert storage.read(object_path='workers/1/contract.pdf') == CONTENT


def test_r3_6_missing_file_in_the_bucket_reads_as_none() -> None:
    """An object path without a file gives None instead of an error."""
    storage = BucketFileStorage(bucket=FakeBucket())

    assert storage.read(object_path='workers/1/unknown.pdf') is None


def test_r12_7_file_deleted_from_the_bucket_is_gone() -> None:
    """A deleted file can no longer be read, and deleting it twice is not an error."""
    storage = BucketFileStorage(bucket=FakeBucket())
    storage.save(object_path='workers/1/contract.pdf', content=CONTENT)

    storage.delete(object_path='workers/1/contract.pdf')
    storage.delete(object_path='workers/1/contract.pdf')

    assert storage.read(object_path='workers/1/contract.pdf') is None


def test_r3_6_bucket_of_the_settings_replaces_the_local_folder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With STORAGE_BUCKET set, files go to that bucket and nothing is written locally."""
    monkeypatch.setattr(storage_module.storage, 'Client', FakeClient)
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('DATABASE_URL', 'postgresql+psycopg://user:password@localhost/database')
    monkeypatch.setenv('STORAGE_BUCKET', 'example-dimonapp-documents')
    monkeypatch.setenv('STORAGE_FOLDER', str(tmp_path / 'documents'))
    settings = load_settings()

    storage = build_file_storage(
        storage_bucket=settings.storage_bucket,
        storage_folder=settings.storage_folder,
    )
    storage.save(object_path='a.pdf', content=CONTENT)

    assert isinstance(storage, BucketFileStorage)
    assert FakeClient.bucket_names == ['example-dimonapp-documents']
    assert not (tmp_path / 'documents').exists()
