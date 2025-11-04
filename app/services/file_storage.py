"""
File Storage Service

Handles local filesystem storage for delivered research data.
Stores files in /data/deliveries/{request_id}/ directory structure.
"""

import os
import shutil
import zipfile
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging
import pandas as pd

logger = logging.getLogger(__name__)


class FileStorageService:
    """Manages local filesystem storage for research data deliveries"""

    def __init__(self, base_path: str = None):
        """
        Initialize file storage service

        Args:
            base_path: Base directory for deliveries (default: /data/deliveries)
        """
        if base_path is None:
            # Use environment variable or default
            base_path = os.getenv("DATA_DELIVERY_PATH", "/data/deliveries")

        self.base_path = Path(base_path)
        self._ensure_base_directory()

    def _ensure_base_directory(self):
        """Create base delivery directory if it doesn't exist"""
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Delivery base directory ready: {self.base_path}")
        except Exception as e:
            logger.error(f"Failed to create delivery directory: {e}")
            raise

    def _get_request_directory(self, request_id: str) -> Path:
        """Get directory path for a specific request"""
        request_dir = self.base_path / request_id
        request_dir.mkdir(parents=True, exist_ok=True)
        return request_dir

    def save_csv(
        self,
        request_id: str,
        filename: str,
        dataframe: pd.DataFrame,
        include_index: bool = False,
    ) -> str:
        """
        Save DataFrame as CSV file

        Args:
            request_id: Research request ID
            filename: Name of CSV file (e.g., "patient_demographics.csv")
            dataframe: Pandas DataFrame to save
            include_index: Whether to include DataFrame index in CSV

        Returns:
            Absolute file path
        """
        try:
            request_dir = self._get_request_directory(request_id)
            file_path = request_dir / filename

            # Save CSV with UTF-8 encoding
            dataframe.to_csv(file_path, index=include_index, encoding="utf-8")

            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            logger.info(
                f"Saved CSV: {filename} ({len(dataframe)} rows, {file_size_mb:.2f} MB) for request {request_id}"
            )

            return str(file_path)

        except Exception as e:
            logger.error(f"Failed to save CSV {filename} for request {request_id}: {e}")
            raise

    def save_text_file(self, request_id: str, filename: str, content: str) -> str:
        """
        Save text file (e.g., data dictionary, QA report)

        Args:
            request_id: Research request ID
            filename: Name of text file
            content: Text content

        Returns:
            Absolute file path
        """
        try:
            request_dir = self._get_request_directory(request_id)
            file_path = request_dir / filename

            file_path.write_text(content, encoding="utf-8")

            logger.info(f"Saved text file: {filename} for request {request_id}")
            return str(file_path)

        except Exception as e:
            logger.error(f"Failed to save text file {filename} for request {request_id}: {e}")
            raise

    def save_data_package(
        self,
        request_id: str,
        data_files: Dict[str, pd.DataFrame],
        metadata_files: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Save complete data package with CSVs and metadata

        Args:
            request_id: Research request ID
            data_files: Dict mapping filename to DataFrame (e.g., {"patients.csv": df})
            metadata_files: Dict mapping filename to text content (e.g., {"README.txt": "..."})

        Returns:
            Dict with:
                - file_list: List of saved filenames
                - file_paths: List of absolute paths
                - total_size_mb: Total package size in MB
                - delivery_location: Request directory path
        """
        try:
            request_dir = self._get_request_directory(request_id)
            saved_files = []
            file_paths = []

            # Save CSV files
            for filename, dataframe in data_files.items():
                file_path = self.save_csv(request_id, filename, dataframe)
                saved_files.append(filename)
                file_paths.append(file_path)

            # Save metadata files
            for filename, content in metadata_files.items():
                file_path = self.save_text_file(request_id, filename, content)
                saved_files.append(filename)
                file_paths.append(file_path)

            # Calculate total size
            total_size_bytes = sum(Path(fp).stat().st_size for fp in file_paths)
            total_size_mb = total_size_bytes / (1024 * 1024)

            logger.info(
                f"Saved data package for request {request_id}: "
                f"{len(saved_files)} files, {total_size_mb:.2f} MB"
            )

            return {
                "file_list": saved_files,
                "file_paths": file_paths,
                "total_size_mb": round(total_size_mb, 2),
                "delivery_location": str(request_dir),
            }

        except Exception as e:
            logger.error(f"Failed to save data package for request {request_id}: {e}")
            raise

    def list_files(self, request_id: str) -> List[Dict[str, Any]]:
        """
        List all files for a request with metadata

        Args:
            request_id: Research request ID

        Returns:
            List of dicts with filename, path, size_mb, modified_at
        """
        try:
            request_dir = self._get_request_directory(request_id)

            if not request_dir.exists():
                return []

            files = []
            for file_path in request_dir.iterdir():
                if file_path.is_file():
                    stat = file_path.stat()
                    files.append(
                        {
                            "filename": file_path.name,
                            "path": str(file_path),
                            "size_mb": round(stat.st_size / (1024 * 1024), 2),
                            "modified_at": stat.st_mtime,
                        }
                    )

            # Sort by filename
            files.sort(key=lambda x: x["filename"])

            return files

        except Exception as e:
            logger.error(f"Failed to list files for request {request_id}: {e}")
            return []

    def get_file_path(self, request_id: str, filename: str) -> Optional[Path]:
        """
        Get absolute path for a specific file

        Args:
            request_id: Research request ID
            filename: Name of file

        Returns:
            Path object if file exists, None otherwise
        """
        file_path = self._get_request_directory(request_id) / filename

        if file_path.exists() and file_path.is_file():
            return file_path

        return None

    def create_download_zip(self, request_id: str, zip_filename: str = None) -> Optional[Path]:
        """
        Create ZIP archive of all files for a request

        Args:
            request_id: Research request ID
            zip_filename: Name of ZIP file (default: {request_id}_data.zip)

        Returns:
            Path to ZIP file
        """
        try:
            request_dir = self._get_request_directory(request_id)

            if not request_dir.exists() or not any(request_dir.iterdir()):
                logger.warning(f"No files to zip for request {request_id}")
                return None

            # Create ZIP filename
            if zip_filename is None:
                zip_filename = f"{request_id}_data_package.zip"

            zip_path = request_dir / zip_filename

            # Create ZIP archive
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for file_path in request_dir.iterdir():
                    if file_path.is_file() and file_path.name != zip_filename:
                        # Add file to ZIP with just the filename (no directory structure)
                        zipf.write(file_path, arcname=file_path.name)

            zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
            logger.info(
                f"Created ZIP archive: {zip_filename} ({zip_size_mb:.2f} MB) for request {request_id}"
            )

            return zip_path

        except Exception as e:
            logger.error(f"Failed to create ZIP for request {request_id}: {e}")
            return None

    def delete_request_data(self, request_id: str) -> bool:
        """
        Delete all files for a request (use with caution!)

        Args:
            request_id: Research request ID

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            request_dir = self._get_request_directory(request_id)

            if request_dir.exists():
                shutil.rmtree(request_dir)
                logger.info(f"Deleted data package for request {request_id}")
                return True

            logger.warning(f"No data package found for request {request_id}")
            return False

        except Exception as e:
            logger.error(f"Failed to delete data package for request {request_id}: {e}")
            return False

    def get_storage_stats(self) -> Dict[str, Any]:
        """
        Get storage usage statistics

        Returns:
            Dict with total_requests, total_size_mb, total_files
        """
        try:
            if not self.base_path.exists():
                return {"total_requests": 0, "total_size_mb": 0, "total_files": 0}

            total_requests = 0
            total_size_bytes = 0
            total_files = 0

            for request_dir in self.base_path.iterdir():
                if request_dir.is_dir():
                    total_requests += 1
                    for file_path in request_dir.iterdir():
                        if file_path.is_file():
                            total_files += 1
                            total_size_bytes += file_path.stat().st_size

            return {
                "total_requests": total_requests,
                "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
                "total_files": total_files,
            }

        except Exception as e:
            logger.error(f"Failed to get storage stats: {e}")
            return {"total_requests": 0, "total_size_mb": 0, "total_files": 0}
