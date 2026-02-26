import os

# use as a second param "sqlite" or "mongo"
DATABASE_TYPE = os.getenv("DATABASE_TYPE", "sqlite")
