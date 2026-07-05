import asyncio
import logging

logger = logging.getLogger(__name__)


class IdentServer:
    def __init__(self, ident: str = "epicchat", port: int = 113):
        self.ident = ident
        self.port = port
        self._server = None

    async def start(self):
        try:
            self._server = await asyncio.start_server(
                self._handle, host="0.0.0.0", port=self.port
            )
            logger.info(f"identd listening on port {self.port}")
        except PermissionError:
            logger.warning(f"identd: no permission for port {self.port} (run as admin)")
        except OSError as e:
            logger.warning(f"identd: {e}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            data = await asyncio.wait_for(reader.readline(), timeout=10)
            if not data:
                return
            query = data.decode("ascii", errors="replace").strip()
            # Format: "PORT_ON_SERVER, PORT_ON_CLIENT"
            parts = query.split(",")
            if len(parts) == 2:
                response = f"{parts[0].strip()}, {parts[1].strip()} : USERID : WIN32 : {self.ident}\r\n"
                writer.write(response.encode("ascii"))
                await writer.drain()
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass
        finally:
            writer.close()
