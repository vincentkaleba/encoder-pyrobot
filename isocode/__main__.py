#!/usr/bin/env python3
"""Point d'entrée principal de l'application IsoCode"""
import asyncio
import signal
from isocode.utils.telegram.clients import initialize_clients, shutdown_clients

async def main():
    """Fonction principale asynchrone"""
    logger.info("Démarrage de l'application IsoCode...")
    await initialize_clients()

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    from isocode import logger

    loop = asyncio.get_event_loop()
    for signame in ('SIGINT', 'SIGTERM'):
        loop.add_signal_handler(
            getattr(signal, signame),
            lambda: asyncio.create_task(shutdown_clients())
        )

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Interruption clavier détectée")
    finally:
        if loop.is_running():
            loop.run_until_complete(shutdown_clients())
        loop.close()
        logger.info("Application arrêtée proprement")