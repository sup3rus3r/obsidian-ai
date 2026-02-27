from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from bson import ObjectId


class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v, handler):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)

    @classmethod
    def __get_pydantic_json_schema__(cls, schema, handler):
        return {"type": "string"}


class UserMongo(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    username: str
    email: str
    role: str
    hashed_password: str
    permissions: Optional[dict] = None
    totp_secret: Optional[str] = None
    totp_enabled: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {ObjectId: str},
    }


class UserCollection:
    collection_name = "users"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("username", unique=True)
        await collection.create_index("email", unique=True)

    @classmethod
    async def find_by_username(cls, db, username: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"username": username})

    @classmethod
    async def find_by_email(cls, db, email: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"email": email})

    @classmethod
    async def create(cls, db, user_data: dict) -> dict:
        collection = db[cls.collection_name]
        result = await collection.insert_one(user_data)
        user_data["_id"] = result.inserted_id
        return user_data

    @classmethod
    async def find_by_id(cls, db, user_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(user_id)})

    @classmethod
    async def update_role(cls, db, user_id: str, new_role: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        result = await collection.find_one_and_update(
            {"_id": ObjectId(user_id)},
            {"$set": {"role": new_role}},
            return_document=True
        )
        return result

    @classmethod
    async def find_all(cls, db) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({})
        return await cursor.to_list(length=1000)

    @classmethod
    async def find_admin_ids(cls, db) -> list[str]:
        """Return list of user_id strings for all admin users."""
        collection = db[cls.collection_name]
        cursor = collection.find({"role": "admin"}, {"_id": 1})
        return [str(doc["_id"]) async for doc in cursor]

    @classmethod
    async def update_user(cls, db, user_id: str, updates: dict) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one_and_update(
            {"_id": ObjectId(user_id)},
            {"$set": updates},
            return_document=True
        )

    @classmethod
    async def update_password(cls, db, user_id: str, hashed_password: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one_and_update(
            {"_id": ObjectId(user_id)},
            {"$set": {"hashed_password": hashed_password}},
            return_document=True
        )

    @classmethod
    async def update_totp(cls, db, user_id: str, totp_secret: Optional[str], totp_enabled: bool) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one_and_update(
            {"_id": ObjectId(user_id)},
            {"$set": {"totp_secret": totp_secret, "totp_enabled": totp_enabled}},
            return_document=True
        )

    @classmethod
    async def delete_user(cls, db, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.delete_one({"_id": ObjectId(user_id)})
        return result.deleted_count > 0


class APIClientMongo(BaseModel):
    """API client model for MongoDB."""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    name            : str
    client_id       : str
    hashed_secret   : str
    created_by      : str
    is_active       : bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "json_encoders": {ObjectId: str},
    }


class APIClientCollection:
    """Collection helper for API clients in MongoDB."""
    collection_name = "api_clients"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("client_id", unique=True)

    @classmethod
    async def find_by_client_id(cls, db, client_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"client_id": client_id, "is_active": True})

    @classmethod
    async def find_by_user(cls, db, user_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"created_by": user_id})
        return await cursor.to_list(length=100)

    @classmethod
    async def create(cls, db, client_data: dict) -> dict:
        collection = db[cls.collection_name]
        result = await collection.insert_one(client_data)
        client_data["_id"] = result.inserted_id
        return client_data

    @classmethod
    async def deactivate(cls, db, client_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.update_one(
            {"client_id": client_id, "created_by": user_id},
            {"$set": {"is_active": False}}
        )
        return result.modified_count > 0


# ============================================================================
# Obsidian AI Collections
# ============================================================================

class LLMProviderCollection:
    collection_name = "llm_providers"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("user_id")

    @classmethod
    async def find_by_user(cls, db, user_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"user_id": user_id, "is_active": True})
        return await cursor.to_list(length=100)

    @classmethod
    async def find_by_id(cls, db, provider_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(provider_id)})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("is_active", True)
        data.setdefault("created_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def update(cls, db, provider_id: str, user_id: str, updates: dict) -> Optional[dict]:
        collection = db[cls.collection_name]
        updates["updated_at"] = datetime.utcnow()
        return await collection.find_one_and_update(
            {"_id": ObjectId(provider_id), "user_id": user_id},
            {"$set": updates},
            return_document=True
        )

    @classmethod
    async def delete(cls, db, provider_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.update_one(
            {"_id": ObjectId(provider_id), "user_id": user_id},
            {"$set": {"is_active": False}}
        )
        return result.modified_count > 0


class AgentCollection:
    collection_name = "agents"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("user_id")

    @classmethod
    async def find_by_user(cls, db, user_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"user_id": user_id, "is_active": True})
        return await cursor.to_list(length=100)

    @classmethod
    async def find_by_id(cls, db, agent_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(agent_id)})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("is_active", True)
        data.setdefault("created_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def update(cls, db, agent_id: str, user_id: str, updates: dict) -> Optional[dict]:
        collection = db[cls.collection_name]
        updates["updated_at"] = datetime.utcnow()
        return await collection.find_one_and_update(
            {"_id": ObjectId(agent_id), "user_id": user_id},
            {"$set": updates},
            return_document=True
        )

    @classmethod
    async def delete(cls, db, agent_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.update_one(
            {"_id": ObjectId(agent_id), "user_id": user_id},
            {"$set": {"is_active": False}}
        )
        return result.modified_count > 0


class TeamCollection:
    collection_name = "teams"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("user_id")

    @classmethod
    async def find_by_user(cls, db, user_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"user_id": user_id, "is_active": True})
        return await cursor.to_list(length=100)

    @classmethod
    async def find_by_id(cls, db, team_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(team_id)})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("is_active", True)
        data.setdefault("created_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def update(cls, db, team_id: str, user_id: str, updates: dict) -> Optional[dict]:
        collection = db[cls.collection_name]
        updates["updated_at"] = datetime.utcnow()
        return await collection.find_one_and_update(
            {"_id": ObjectId(team_id), "user_id": user_id},
            {"$set": updates},
            return_document=True
        )

    @classmethod
    async def delete(cls, db, team_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.update_one(
            {"_id": ObjectId(team_id), "user_id": user_id},
            {"$set": {"is_active": False}}
        )
        return result.modified_count > 0


class WorkflowCollection:
    collection_name = "workflows"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("user_id")

    @classmethod
    async def find_by_user(cls, db, user_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"user_id": user_id, "is_active": True})
        return await cursor.to_list(length=100)

    @classmethod
    async def find_by_id(cls, db, workflow_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(workflow_id)})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("is_active", True)
        data.setdefault("created_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def update(cls, db, workflow_id: str, user_id: str, updates: dict) -> Optional[dict]:
        collection = db[cls.collection_name]
        updates["updated_at"] = datetime.utcnow()
        return await collection.find_one_and_update(
            {"_id": ObjectId(workflow_id), "user_id": user_id},
            {"$set": updates},
            return_document=True
        )

    @classmethod
    async def delete(cls, db, workflow_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.update_one(
            {"_id": ObjectId(workflow_id), "user_id": user_id},
            {"$set": {"is_active": False}}
        )
        return result.modified_count > 0


class WorkflowRunCollection:
    collection_name = "workflow_runs"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("user_id")
        await collection.create_index("workflow_id")

    @classmethod
    async def find_by_user(cls, db, user_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"user_id": user_id}).sort("started_at", -1)
        return await cursor.to_list(length=100)

    @classmethod
    async def find_by_workflow(cls, db, workflow_id: str, user_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"workflow_id": workflow_id, "user_id": user_id}).sort("started_at", -1)
        return await cursor.to_list(length=100)

    @classmethod
    async def find_by_id(cls, db, run_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(run_id)})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("status", "running")
        data.setdefault("current_step", 0)
        data.setdefault("started_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def update(cls, db, run_id: str, updates: dict) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one_and_update(
            {"_id": ObjectId(run_id)},
            {"$set": updates},
            return_document=True
        )

    @classmethod
    async def delete(cls, db, run_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.delete_one({"_id": ObjectId(run_id), "user_id": user_id})
        return result.deleted_count > 0


class SessionCollection:
    collection_name = "sessions"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("user_id")
        await collection.create_index([("entity_type", 1), ("entity_id", 1)])

    @classmethod
    async def find_by_user(cls, db, user_id: str, entity_type: str = None, entity_id: str = None) -> list[dict]:
        collection = db[cls.collection_name]
        query = {"user_id": user_id, "is_active": True}
        if entity_type:
            query["entity_type"] = entity_type
        if entity_id:
            query["entity_id"] = entity_id
        cursor = collection.find(query).sort("updated_at", -1)
        return await cursor.to_list(length=100)

    @classmethod
    async def find_by_id(cls, db, session_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(session_id)})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("is_active", True)
        data.setdefault("created_at", datetime.utcnow())
        data.setdefault("updated_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def update(cls, db, session_id: str, updates: dict) -> Optional[dict]:
        collection = db[cls.collection_name]
        updates["updated_at"] = datetime.utcnow()
        return await collection.find_one_and_update(
            {"_id": ObjectId(session_id)},
            {"$set": updates},
            return_document=True
        )

    @classmethod
    async def delete(cls, db, session_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        # Verify ownership before deleting
        session = await collection.find_one({"_id": ObjectId(session_id), "user_id": user_id})
        if not session:
            return False
        # Hard delete the session
        await collection.delete_one({"_id": ObjectId(session_id)})
        # Cascade: hard delete all messages and attachments for this session
        await db["messages"].delete_many({"session_id": session_id})
        await db["file_attachments"].delete_many({"session_id": session_id})
        return True


class MessageCollection:
    collection_name = "messages"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("session_id")
        await collection.create_index("created_at")

    @classmethod
    async def find_by_session(cls, db, session_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"session_id": session_id}).sort("created_at", 1).skip(offset).limit(limit)
        return await cursor.to_list(length=limit)

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("created_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def update_metadata(cls, db, message_id: str, metadata: dict) -> None:
        collection = db[cls.collection_name]
        import json as _json
        await collection.update_one(
            {"_id": ObjectId(message_id)},
            {"$set": {"metadata_json": _json.dumps(metadata)}},
        )


class ToolDefinitionCollection:
    collection_name = "tool_definitions"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("user_id")

    @classmethod
    async def find_by_user(cls, db, user_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"user_id": user_id, "is_active": True})
        return await cursor.to_list(length=100)

    @classmethod
    async def find_by_id(cls, db, tool_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(tool_id)})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("is_active", True)
        data.setdefault("created_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def update(cls, db, tool_id: str, user_id: str, updates: dict) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one_and_update(
            {"_id": ObjectId(tool_id), "user_id": user_id},
            {"$set": updates},
            return_document=True
        )

    @classmethod
    async def delete(cls, db, tool_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.update_one(
            {"_id": ObjectId(tool_id), "user_id": user_id},
            {"$set": {"is_active": False}}
        )
        return result.modified_count > 0


class MCPServerCollection:
    collection_name = "mcp_servers"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("user_id")

    @classmethod
    async def find_by_user(cls, db, user_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"user_id": user_id, "is_active": True})
        return await cursor.to_list(length=100)

    @classmethod
    async def find_by_id(cls, db, server_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(server_id)})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("is_active", True)
        data.setdefault("created_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def update(cls, db, server_id: str, user_id: str, updates: dict) -> Optional[dict]:
        collection = db[cls.collection_name]
        updates["updated_at"] = datetime.utcnow()
        return await collection.find_one_and_update(
            {"_id": ObjectId(server_id), "user_id": user_id},
            {"$set": updates},
            return_document=True
        )

    @classmethod
    async def delete(cls, db, server_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.update_one(
            {"_id": ObjectId(server_id), "user_id": user_id},
            {"$set": {"is_active": False}}
        )
        return result.modified_count > 0


class FileAttachmentCollection:
    collection_name = "file_attachments"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("session_id")
        await collection.create_index("user_id")

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("created_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def find_by_session(cls, db, session_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"session_id": session_id})
        return await cursor.to_list(length=500)

    @classmethod
    async def find_by_id(cls, db, file_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(file_id)})


class UserSecretCollection:
    collection_name = "user_secrets"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("user_id")

    @classmethod
    async def find_by_user(cls, db, user_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"user_id": user_id}).sort("created_at", -1)
        return await cursor.to_list(length=100)

    @classmethod
    async def find_by_id(cls, db, secret_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(secret_id)})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("created_at", datetime.utcnow())
        data.setdefault("updated_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def update(cls, db, secret_id: str, user_id: str, updates: dict) -> Optional[dict]:
        collection = db[cls.collection_name]
        updates["updated_at"] = datetime.utcnow()
        return await collection.find_one_and_update(
            {"_id": ObjectId(secret_id), "user_id": user_id},
            {"$set": updates},
            return_document=True
        )

    @classmethod
    async def delete(cls, db, secret_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.delete_one(
            {"_id": ObjectId(secret_id), "user_id": user_id}
        )
        return result.deleted_count > 0


class KnowledgeBaseCollection:
    collection_name = "knowledge_bases"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("user_id")
        await collection.create_index("is_shared")

    @classmethod
    async def find_accessible(cls, db, user_id: str) -> list[dict]:
        """Return KBs owned by user + shared KBs."""
        collection = db[cls.collection_name]
        cursor = collection.find({
            "is_active": True,
            "$or": [{"user_id": user_id}, {"is_shared": True}],
        })
        return await cursor.to_list(length=200)

    @classmethod
    async def find_by_id(cls, db, kb_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(kb_id), "is_active": True})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("is_active", True)
        data.setdefault("is_shared", False)
        data.setdefault("created_at", datetime.utcnow())
        data.setdefault("updated_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def update(cls, db, kb_id: str, user_id: str, updates: dict) -> Optional[dict]:
        collection = db[cls.collection_name]
        updates["updated_at"] = datetime.utcnow()
        return await collection.find_one_and_update(
            {"_id": ObjectId(kb_id), "user_id": user_id},
            {"$set": updates},
            return_document=True,
        )

    @classmethod
    async def delete(cls, db, kb_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.update_one(
            {"_id": ObjectId(kb_id), "user_id": user_id},
            {"$set": {"is_active": False}},
        )
        return result.modified_count > 0


class WorkflowScheduleCollection:
    collection_name = "workflow_schedules"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("workflow_id")
        await collection.create_index("user_id")
        await collection.create_index("is_active")

    @classmethod
    async def find_all_active(cls, db) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"is_active": True})
        return await cursor.to_list(length=None)

    @classmethod
    async def find_by_workflow(cls, db, workflow_id: str, user_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"workflow_id": workflow_id, "user_id": user_id})
        return await cursor.to_list(length=100)

    @classmethod
    async def find_by_id(cls, db, schedule_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(schedule_id)})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("is_active", True)
        data.setdefault("created_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def update(cls, db, schedule_id: str, user_id: str, updates: dict) -> Optional[dict]:
        collection = db[cls.collection_name]
        updates["updated_at"] = datetime.utcnow()
        return await collection.find_one_and_update(
            {"_id": ObjectId(schedule_id), "user_id": user_id},
            {"$set": updates},
            return_document=True,
        )

    @classmethod
    async def delete(cls, db, schedule_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.delete_one(
            {"_id": ObjectId(schedule_id), "user_id": user_id}
        )
        return result.deleted_count > 0


class KBDocumentCollection:
    collection_name = "kb_documents"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("kb_id")

    @classmethod
    async def find_by_kb(cls, db, kb_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"kb_id": kb_id}).sort("created_at", 1)
        return await cursor.to_list(length=500)

    @classmethod
    async def count_for_kb(cls, db, kb_id: str) -> int:
        collection = db[cls.collection_name]
        return await collection.count_documents({"kb_id": kb_id})

    @classmethod
    async def find_by_id(cls, db, doc_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(doc_id)})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("indexed", False)
        data.setdefault("created_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def delete(cls, db, doc_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.delete_one({"_id": ObjectId(doc_id)})
        return result.deleted_count > 0


class HITLApprovalCollection:
    """Collection helper for human-in-the-loop approval records in MongoDB."""
    collection_name = "hitl_approvals"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("session_id")
        await collection.create_index("status")

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("created_at", datetime.utcnow())
        data.setdefault("status", "pending")
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def find_pending_by_session(cls, db, session_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"session_id": session_id, "status": "pending"})
        return await cursor.to_list(length=10)

    @classmethod
    async def find_by_id(cls, db, approval_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(approval_id)})

    @classmethod
    async def update_status(cls, db, approval_id: str, status: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one_and_update(
            {"_id": ObjectId(approval_id)},
            {"$set": {"status": status, "resolved_at": datetime.utcnow()}},
            return_document=True,
        )

    @classmethod
    async def deny_all_pending(cls, db) -> int:
        """Auto-deny all pending approvals (called on server startup)."""
        collection = db[cls.collection_name]
        result = await collection.update_many(
            {"status": "pending"},
            {"$set": {"status": "denied", "resolved_at": datetime.utcnow()}},
        )
        return result.modified_count


class ToolProposalCollection:
    """Collection helper for agent-proposed tool definitions awaiting user approval in MongoDB."""
    collection_name = "tool_proposals"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("session_id")
        await collection.create_index("status")

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("created_at", datetime.utcnow())
        data.setdefault("status", "pending")
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def find_pending_by_session(cls, db, session_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"session_id": session_id, "status": "pending"})
        return await cursor.to_list(length=10)

    @classmethod
    async def find_by_id(cls, db, proposal_id: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"_id": ObjectId(proposal_id)})

    @classmethod
    async def update_status(cls, db, proposal_id: str, status: str, extra: dict = None) -> Optional[dict]:
        collection = db[cls.collection_name]
        update_fields = {"status": status, "resolved_at": datetime.utcnow()}
        if extra:
            update_fields.update(extra)
        return await collection.find_one_and_update(
            {"_id": ObjectId(proposal_id)},
            {"$set": update_fields},
            return_document=True,
        )

    @classmethod
    async def reject_all_pending(cls, db) -> int:
        """Auto-reject all pending proposals (called on server startup)."""
        collection = db[cls.collection_name]
        result = await collection.update_many(
            {"status": "pending"},
            {"$set": {"status": "rejected", "resolved_at": datetime.utcnow()}},
        )
        return result.modified_count


class AgentMemoryCollection:
    """Collection helper for long-term agent memory facts in MongoDB."""
    collection_name = "agent_memories"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index([("agent_id", 1), ("user_id", 1)])
        await collection.create_index([("agent_id", 1), ("user_id", 1), ("key", 1)])

    @classmethod
    async def find_by_agent_user(cls, db, agent_id: str, user_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find(
            {"agent_id": agent_id, "user_id": user_id}
        ).sort("created_at", -1).limit(50)
        return await cursor.to_list(length=50)

    @classmethod
    async def count_by_agent_user(cls, db, agent_id: str, user_id: str) -> int:
        collection = db[cls.collection_name]
        return await collection.count_documents({"agent_id": agent_id, "user_id": user_id})

    @classmethod
    async def find_by_key(cls, db, agent_id: str, user_id: str, key: str) -> Optional[dict]:
        collection = db[cls.collection_name]
        return await collection.find_one({"agent_id": agent_id, "user_id": user_id, "key": key})

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("created_at", datetime.utcnow())
        data.setdefault("confidence", 1.0)
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def upsert_by_key(cls, db, agent_id: str, user_id: str, key: str, updates: dict) -> dict:
        """Update an existing memory by key, or insert if not found."""
        collection = db[cls.collection_name]
        updates.setdefault("updated_at", datetime.utcnow())
        return await collection.find_one_and_update(
            {"agent_id": agent_id, "user_id": user_id, "key": key},
            {"$set": updates, "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
            return_document=True,
        )

    @classmethod
    async def delete_by_id(cls, db, memory_id: str, user_id: str) -> bool:
        collection = db[cls.collection_name]
        result = await collection.delete_one({"_id": ObjectId(memory_id), "user_id": user_id})
        return result.deleted_count > 0

    @classmethod
    async def delete_all_by_agent_user(cls, db, agent_id: str, user_id: str) -> int:
        collection = db[cls.collection_name]
        result = await collection.delete_many({"agent_id": agent_id, "user_id": user_id})
        return result.deleted_count

    @classmethod
    async def evict_oldest_low_confidence(cls, db, agent_id: str, user_id: str, count: int) -> int:
        """Delete up to `count` oldest memories with confidence < 0.5 to stay under the cap."""
        collection = db[cls.collection_name]
        cursor = collection.find(
            {"agent_id": agent_id, "user_id": user_id, "confidence": {"$lt": 0.5}}
        ).sort("created_at", 1).limit(count)
        docs = await cursor.to_list(length=count)
        if not docs:
            return 0
        ids = [d["_id"] for d in docs]
        result = await collection.delete_many({"_id": {"$in": ids}})
        return result.deleted_count


class TraceSpanCollection:
    """Collection helper for execution trace spans in MongoDB."""
    collection_name = "trace_spans"

    @classmethod
    async def create_indexes(cls, db):
        collection = db[cls.collection_name]
        await collection.create_index("session_id")
        await collection.create_index("workflow_run_id")
        await collection.create_index([("session_id", 1), ("sequence", 1)])
        await collection.create_index([("workflow_run_id", 1), ("sequence", 1)])

    @classmethod
    async def create(cls, db, data: dict) -> dict:
        collection = db[cls.collection_name]
        data.setdefault("created_at", datetime.utcnow())
        result = await collection.insert_one(data)
        data["_id"] = result.inserted_id
        return data

    @classmethod
    async def find_by_session(cls, db, session_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"session_id": session_id}).sort("sequence", 1)
        return await cursor.to_list(length=1000)

    @classmethod
    async def find_by_workflow_run(cls, db, workflow_run_id: str) -> list[dict]:
        collection = db[cls.collection_name]
        cursor = collection.find({"workflow_run_id": workflow_run_id}).sort("sequence", 1)
        return await cursor.to_list(length=1000)
