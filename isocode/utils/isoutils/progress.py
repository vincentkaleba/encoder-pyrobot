

def create_progress_bar(percent: float, length: int = 10) -> str:
    """
    Crée une barre de progression visuelle.
    """
    progress = min(100, max(0, percent))
    filled = int(progress / 100 * length)
    empty = length - filled
    return f"[{'█' * filled}{'░' * empty}]"

def humanbytes(size: float) -> str:
    """
    Convertit des octets en format lisible
    """
    units = ["B", "Ko", "Mo", "Go", "To"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.2f} {units[index]}"