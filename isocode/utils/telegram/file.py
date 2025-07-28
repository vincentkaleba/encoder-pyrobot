from pyrogram import Client
from config import settings, logger
from isocode.utils.isoutils.progress import create_progress_bar, humanbytes
import os
import hashlib
import zipfile
import tarfile
import asyncio
import shutil
import tempfile
import re
from typing import Tuple, Optional, Dict, List, Union, BinaryIO, Callable
from pathlib import Path
import subprocess
import mimetypes
import aiohttp
import aiofiles

async def get_filesize(client: Client, file_id: str) -> int:
    """Obtient la taille d'un fichier à partir de son file_id"""
    try:
        file = await client.get_file(file_id)
        return file.file_size
    except Exception as e:
        logger.error(f"Erreur obtention taille fichier {file_id}: {e}")
        return 0

def split_file(
    file_path: str,
    chunk_size: int = 95 * 1024 * 1024,  # 95MB (limite Telegram)
    output_dir: Optional[str] = None,
    buffer_size: int = 10 * 1024 * 1024  # 10MB
) -> List[str]:
    """
    Divise un fichier volumineux en plusieurs parties

    :param file_path: Chemin du fichier source
    :param chunk_size: Taille max par partie (défaut: 95MB)
    :param output_dir: Répertoire de sortie (défaut: même dossier)
    :param buffer_size: Taille du buffer de lecture
    :return: Liste des chemins des parties
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {file_path}")

    file_size = file_path.stat().st_size
    if file_size <= chunk_size:
        return [str(file_path)]

    output_dir = Path(output_dir) if output_dir else file_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = file_path.name
    parts = []
    part_num = 1

    with open(file_path, 'rb') as f:
        while True:
            part_name = f"{base_name}.part{part_num:03d}"
            part_path = output_dir / part_name
            bytes_written = 0

            with open(part_path, 'wb') as part_file:
                while bytes_written < chunk_size:
                    read_size = min(buffer_size, chunk_size - bytes_written)
                    chunk = f.read(read_size)
                    if not chunk:
                        break
                    part_file.write(chunk)
                    bytes_written += len(chunk)

            if bytes_written == 0:
                part_path.unlink(missing_ok=True)
                break

            parts.append(str(part_path))
            part_num += 1

    logger.info(f"Fichier divisé en {len(parts)} parties")
    return parts

def join_files(
    parts: List[str],
    output_path: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    buffer_size: int = 10 * 1024 * 1024  # 10MB
) -> str:
    """
    Reconstruit un fichier à partir de ses parties

    :param parts: Liste des parties dans l'ordre
    :param output_path: Chemin du fichier reconstruit
    :param progress_callback: Callback de progression
    :param buffer_size: Taille du buffer d'écriture
    :return: Chemin du fichier reconstruit
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_size = sum(Path(part).stat().st_size for part in parts)
    processed = 0

    with open(output_path, 'wb') as outfile:
        for part in parts:
            part_size = Path(part).stat().st_size
            with open(part, 'rb') as infile:
                while True:
                    chunk = infile.read(buffer_size)
                    if not chunk:
                        break
                    outfile.write(chunk)
                    processed += len(chunk)
                    if progress_callback:
                        progress_callback(processed, total_size)

    logger.info(f"Fichier reconstruit: {output_path} ({humanbytes(total_size)})")
    return str(output_path)

def compress_file(
    file_path: str,
    compression_type: str = "zip",
    password: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    buffer_size: int = 10 * 1024 * 1024  # 10MB
) -> str:
    """
    Compresse un fichier/dossier

    :param file_path: Chemin du fichier/dossier
    :param compression_type: 'zip' ou 'tar'
    :param password: Mot de passe pour archives zip
    :param progress_callback: Callback de progression
    :param buffer_size: Taille du buffer de lecture
    :return: Chemin de l'archive
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {file_path}")

    is_dir = file_path.is_dir()
    output_path = f"{file_path}.{compression_type}"
    processed = 0

    if compression_type == "zip":
        with zipfile.ZipFile(
            output_path,
            'w',
            zipfile.ZIP_DEFLATED,
            compresslevel=6
        ) as zipf:
            if password:
                zipf.setpassword(password.encode())

            if is_dir:
                total_size = sum(f.stat().st_size for f in file_path.rglob('*') if f.is_file())
                for file in file_path.rglob('*'):
                    if file.is_file():
                        rel_path = file.relative_to(file_path.parent)
                        with open(file, 'rb') as src:
                            with zipf.open(str(rel_path), 'w') as dest:
                                while True:
                                    chunk = src.read(buffer_size)
                                    if not chunk:
                                        break
                                    dest.write(chunk)
                                    processed += len(chunk)
                                    if progress_callback:
                                        progress_callback(processed, total_size)
            else:
                with open(file_path, 'rb') as src:
                    with zipf.open(file_path.name, 'w') as dest:
                        while True:
                            chunk = src.read(buffer_size)
                            if not chunk:
                                break
                            dest.write(chunk)
                            processed += len(chunk)
                            if progress_callback:
                                progress_callback(processed, file_path.stat().st_size)

    elif compression_type == "tar":
        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(file_path, arcname=file_path.name)
    else:
        raise ValueError(f"Type de compression non supporté: {compression_type}")

    logger.info(f"Fichier compressé: {output_path}")
    return output_path

def decompress_file(
    archive_path: str,
    output_dir: Optional[str] = None,
    password: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    buffer_size: int = 10 * 1024 * 1024  # 10MB
) -> str:
    """
    Décompresse une archive

    :param archive_path: Chemin de l'archive
    :param output_dir: Répertoire de sortie
    :param password: Mot de passe pour archives zip
    :param progress_callback: Callback de progression
    :param buffer_size: Taille du buffer d'écriture
    :return: Chemin du dossier décompressé
    """
    archive_path = Path(archive_path)
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive introuvable: {archive_path}")

    output_dir = Path(output_dir) if output_dir else archive_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    processed = 0

    if archive_path.suffix == '.zip':
        with zipfile.ZipFile(archive_path, 'r') as zipf:
            if password:
                zipf.setpassword(password.encode())

            file_list = zipf.infolist()
            total_size = sum(f.file_size for f in file_list)

            for file in file_list:
                file_path = output_dir / file.filename
                file_path.parent.mkdir(parents=True, exist_ok=True)

                with zipf.open(file) as src, open(file_path, 'wb') as dest:
                    while True:
                        chunk = src.read(buffer_size)
                        if not chunk:
                            break
                        dest.write(chunk)
                        processed += len(chunk)
                        if progress_callback:
                            progress_callback(processed, total_size)

    elif archive_path.suffix in ('.tar', '.gz', '.tgz'):
        with tarfile.open(archive_path, "r:*") as tar:
            members = tar.getmembers()
            total_size = sum(m.size for m in members)

            for member in members:
                tar.extract(member, output_dir)
                processed += member.size
                if progress_callback:
                    progress_callback(processed, total_size)
    else:
        raise ValueError(f"Format d'archive non supporté: {archive_path}")

    logger.info(f"Archive décompressée dans: {output_dir}")
    return str(output_dir)

def calculate_hash(
    file_path: str,
    algorithm: str = "sha256",
    progress_callback: Optional[Callable[[int, int], None]] = None,
    buffer_size: int = 10 * 1024 * 1024  # 10MB
) -> str:
    """
    Calcule le hash d'un fichier

    :param file_path: Chemin du fichier
    :param algorithm: sha256, md5, sha1, etc.
    :param progress_callback: Callback de progression
    :param buffer_size: Taille des blocs à lire
    :return: Hash hexadécimal
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {file_path}")

    hash_func = hashlib.new(algorithm)
    file_size = file_path.stat().st_size
    processed = 0

    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(buffer_size)
            if not chunk:
                break
            hash_func.update(chunk)
            processed += len(chunk)
            if progress_callback:
                progress_callback(processed, file_size)

    return hash_func.hexdigest()

def rename_file(
    file_path: str,
    new_name: str,
    overwrite: bool = False
) -> str:
    """
    Renomme un fichier/dossier

    :param file_path: Chemin actuel
    :param new_name: Nouveau nom (sans chemin)
    :param overwrite: Écraser si existe déjà
    :return: Nouveau chemin complet
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {file_path}")

    new_path = file_path.parent / new_name

    if new_path.exists():
        if overwrite:
            if new_path.is_dir():
                shutil.rmtree(new_path)
            else:
                new_path.unlink()
        else:
            raise FileExistsError(f"Le fichier existe déjà: {new_path}")

    file_path.rename(new_path)
    return str(new_path)

def delete_file(file_path: str, ignore_missing: bool = False):
    """
    Supprime un fichier/dossier récursivement

    :param file_path: Chemin à supprimer
    :param ignore_missing: Ne pas lever d'erreur si absent
    """
    file_path = Path(file_path)
    if not file_path.exists():
        if ignore_missing:
            return
        raise FileNotFoundError(f"Fichier introuvable: {file_path}")

    if file_path.is_dir():
        shutil.rmtree(file_path)
    else:
        file_path.unlink()

def get_file_extension(file_path: str) -> str:
    """
    Obtient l'extension d'un fichier

    :param file_path: Chemin du fichier
    :return: Extension en minuscules (ex: '.mp4')
    """
    return Path(file_path).suffix.lower()

def is_valid_path(path: str) -> bool:
    """
    Vérifie si un chemin est valide

    :param path: Chemin à vérifier
    :return: True si valide, False sinon
    """
    try:
        if re.search(r'[<>:"|?*]', path):
            return False
        Path(path)
        return True
    except Exception:
        return False

def create_temp_dir(prefix: str = "temp_") -> str:
    """
    Crée un répertoire temporaire

    :param prefix: Préfixe du nom du dossier
    :return: Chemin du dossier temporaire
    """
    temp_dir = tempfile.mkdtemp(prefix=prefix)
    logger.debug(f"Répertoire temporaire créé: {temp_dir}")
    return temp_dir

def clean_temp_dir(temp_dir: str):
    """
    Nettoie un répertoire temporaire

    :param temp_dir: Chemin du dossier temporaire
    """
    temp_dir = Path(temp_dir)
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
        logger.debug(f"Répertoire temporaire nettoyé: {temp_dir}")

async def async_copy_file(
    src: str,
    dst: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    buffer_size: int = 10 * 1024 * 1024  # 10MB
) -> str:
    """
    Copie un fichier de manière asynchrone avec progression

    :param src: Chemin source
    :param dst: Chemin destination
    :param progress_callback: Callback de progression
    :param buffer_size: Taille du buffer de copie
    :return: Chemin du fichier copié
    """
    src_path = Path(src)
    if not src_path.exists():
        raise FileNotFoundError(f"Fichier source introuvable: {src}")

    dst_path = Path(dst)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    file_size = src_path.stat().st_size
    processed = 0

    async with aiofiles.open(src, 'rb') as f_src:
        async with aiofiles.open(dst, 'wb') as f_dst:
            while processed < file_size:
                chunk = await f_src.read(buffer_size)
                if not chunk:
                    break
                await f_dst.write(chunk)
                processed += len(chunk)
                if progress_callback:
                    progress_callback(processed, file_size)

    return dst

def get_mime_type(file_path: str) -> str:
    """
    Obtient le type MIME d'un fichier

    :param file_path: Chemin du fichier
    :return: Type MIME (ex: 'video/mp4')
    """
    mime, _ = mimetypes.guess_type(file_path)
    return mime or "application/octet-stream"

def get_file_info(file_path: str) -> Dict[str, Union[str, int]]:
    """
    Obtient les informations détaillées d'un fichier

    :param file_path: Chemin du fichier
    :return: Dictionnaire d'informations
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Fichier introuvable: {file_path}")

    stat = file_path.stat()
    return {
        "path": str(file_path),
        "size": stat.st_size,
        "created": stat.st_ctime,
        "modified": stat.st_mtime,
        "is_dir": file_path.is_dir(),
        "extension": file_path.suffix.lower(),
        "mime_type": get_mime_type(str(file_path))
    }

def create_thumbnail(
    video_path: str,
    output_path: str,
    size: Tuple[int, int] = (320, 320),
    time_position: float = 30.0,
    quality: int = 85
) -> str:
    """
    Crée une miniature pour une vidéo en capturant une image avec ffmpeg.

    :param video_path: Chemin de la vidéo source
    :param output_path: Chemin de sortie de la miniature (image jpg/png)
    :param size: Dimensions (largeur, hauteur)
    :param time_position: Position en secondes pour capturer l'image
    :param quality: Qualité JPEG (1-100)
    :return: Chemin de la miniature générée
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Fichier source introuvable: {video_path}")

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg n'est pas installé ou n'est pas dans le PATH")

    width, height = size
    quality_val = max(2, min(31, 31 - quality // 3))  # Conversion qualité ffmpeg

    ffmpeg_cmd = [
        "ffmpeg",
        "-ss", str(time_position),
        "-i", str(video_path),
        "-vframes", "1",
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
        "-q:v", str(quality_val),
        "-y",
        output_path
    ]

    try:
        subprocess.run(
            ffmpeg_cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if isinstance(e.stderr, str) else e.stderr.decode()
        raise RuntimeError(f"Erreur ffmpeg: {error_msg}") from e

    if not Path(output_path).exists():
        raise RuntimeError("La miniature n'a pas été créée.")

    return output_path

async def async_download_url(
    url: str,
    output_path: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    buffer_size: int = 10 * 1024 * 1024  # 10MB
) -> str:
    """
    Télécharge un fichier depuis une URL de manière asynchrone

    :param url: URL à télécharger
    :param output_path: Chemin de destination
    :param progress_callback: Callback de progression
    :param buffer_size: Taille du buffer de téléchargement
    :return: Chemin du fichier téléchargé
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise RuntimeError(f"Échec téléchargement: HTTP {response.status}")

            total_size = int(response.headers.get('content-length', 0))
            processed = 0

            async with aiofiles.open(output_path, 'wb') as f:
                async for chunk in response.content.iter_chunked(buffer_size):
                    await f.write(chunk)
                    processed += len(chunk)
                    if progress_callback:
                        progress_callback(processed, total_size)

    return str(output_path)

def validate_filename(filename: str) -> str:
    """
    Vérifie si le nom de fichier est valide

    :param filename: Nom du fichier
    :return: Nom du fichier valide
    """
    if len(filename) > 255:
        raise ValueError("Le nom de fichier est trop long (max 255 caractères)")

    if any(char in r'<>:"/\|?*' for char in filename):
        raise ValueError("Le nom de fichier contient des caractères non autorisés")

    return filename