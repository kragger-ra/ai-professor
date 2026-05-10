import os, sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "src"
    ),
)

from data_flow.database import StreamerDatabase


db = StreamerDatabase()
print(db.get_user_data("Ошибка"))