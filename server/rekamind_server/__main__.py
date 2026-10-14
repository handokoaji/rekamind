import uvicorn

from .api import create_app

if __name__ == "__main__":
    # Bind to loopback by default: no authentication exists yet, so the API must
    # not be reachable from the network unless the operator opts in explicitly.
    import os
    uvicorn.run(create_app(), host=os.environ.get("REKAMIND_HOST", "127.0.0.1"),
                port=int(os.environ.get("REKAMIND_PORT", "8787")))
