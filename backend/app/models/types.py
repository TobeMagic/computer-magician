from sqlalchemy import JSON, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB


JSON_DICT = JSON().with_variant(JSONB, "postgresql")
TEXT_ARRAY = JSON().with_variant(ARRAY(Text), "postgresql")
