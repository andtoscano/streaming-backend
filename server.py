from fastapi import FastAPI, APIRouter, HTTPException, Query
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import uuid
from datetime import datetime, timedelta
import httpx
from functools import lru_cache
import time

load_dotenv()

mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
client = AsyncIOMotorClient(mongo_url)
db_name = os.environ.get('DB_NAME', 'streaming_discovery')
db = client[db_name]

TMDB_API_KEY = os.environ.get('TMDB_API_KEY', '')
TMDB_BASE_URL = "https://api.themoviedb.org/3"

class SimpleCache:
    def __init__(self, default_ttl=3600):
        self._cache = {}
        self._timestamps = {}
        self.default_ttl = default_ttl
    def get(self, key):
        if key in self._cache:
            if time.time() - self._timestamps[key] < self.default_ttl:
                return self._cache[key]
            else:
                del self._cache[key]
                del self._timestamps[key]
        return None
    def set(self, key, value, ttl=None):
        self._cache[key] = value
        self._timestamps[key] = time.time()
    def clear(self):
        self._cache.clear()
        self._timestamps.clear()

search_cache = SimpleCache(default_ttl=1800)
provider_cache = SimpleCache(default_ttl=3600)
person_cache = SimpleCache(default_ttl=3600)

app = FastAPI(title="E 'ndoe l'è che la se trova? API")
api_router = APIRouter(prefix="/api")

class StreamingProvider(BaseModel):
    provider_id: int
    provider_name: str
    logo_path: Optional[str] = None

class SearchResult(BaseModel):
    id: int
    title: str
    media_type: str
    poster_path: Optional[str] = None
    overview: Optional[str] = None
    release_date: Optional[str] = None
    vote_average: Optional[float] = None

class PersonResult(BaseModel):
    id: int
    name: str
    profile_path: Optional[str] = None
    known_for_department: Optional[str] = None

class WatchProviderResult(BaseModel):
    content_id: int
    content_title: str
    media_type: str
    poster_path: Optional[str] = None
    flatrate: List[StreamingProvider] = []
    rent: List[StreamingProvider] = []
    buy: List[StreamingProvider] = []
    link: Optional[str] = None

def get_image_url(path: Optional[str], size: str = "w500") -> Optional[str]:
    if path:
        return f"https://image.tmdb.org/t/p/{size}{path}"
    return None

@api_router.get("/")
async def root():
    return {"message": "E 'ndoe l'è che la se trova? API", "status": "online"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy"}

@api_router.get("/search", response_model=List[SearchResult])
async def search_content(query: str = Query(..., min_length=1)):
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB API key not configured")
    cache_key = f"search:{query.lower().strip()}"
    cached_result = search_cache.get(cache_key)
    if cached_result is not None:
        return cached_result
    async with httpx.AsyncClient() as http_client:
        try:
            response = await http_client.get(f"{TMDB_BASE_URL}/search/multi", params={"api_key": TMDB_API_KEY, "query": query, "language": "it-IT", "region": "IT", "include_adult": False}, timeout=15.0)
            response.raise_for_status()
            data = response.json()
            results = []
            for item in data.get("results", []):
                media_type = item.get("media_type")
                if media_type in ["movie", "tv"]:
                    title = item.get("title") if media_type == "movie" else item.get("name")
                    release_date = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
                    results.append(SearchResult(id=item.get("id"), title=title or "Unknown", media_type=media_type, poster_path=get_image_url(item.get("poster_path")), overview=item.get("overview"), release_date=release_date, vote_average=item.get("vote_average")))
            results = results[:20]
            search_cache.set(cache_key, results)
            return results
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/search/person", response_model=List[PersonResult])
async def search_person(query: str = Query(..., min_length=1)):
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB API key not configured")
    cache_key = f"person:{query.lower().strip()}"
    cached_result = person_cache.get(cache_key)
    if cached_result is not None:
        return cached_result
    async with httpx.AsyncClient() as http_client:
        try:
            response = await http_client.get(f"{TMDB_BASE_URL}/search/person", params={"api_key": TMDB_API_KEY, "query": query, "language": "it-IT", "include_adult": False}, timeout=15.0)
            response.raise_for_status()
            data = response.json()
            results = []
            for item in data.get("results", []):
                results.append(PersonResult(id=item.get("id"), name=item.get("name"), profile_path=get_image_url(item.get("profile_path"), "w185"), known_for_department=item.get("known_for_department")))
            results = results[:10]
            person_cache.set(cache_key, results)
            return results
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/person/{person_id}/credits", response_model=List[SearchResult])
async def get_person_credits(person_id: int, role: str = Query("all", enum=["all", "actor", "director"])):
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB API key not configured")
    cache_key = f"credits:{person_id}:{role}"
    cached_result = person_cache.get(cache_key)
    if cached_result is not None:
        return cached_result
    async with httpx.AsyncClient() as http_client:
        try:
            response = await http_client.get(f"{TMDB_BASE_URL}/person/{person_id}/combined_credits", params={"api_key": TMDB_API_KEY, "language": "it-IT"}, timeout=15.0)
            response.raise_for_status()
            data = response.json()
            results = []
            seen_ids = set()
            if role in ["all", "actor"]:
                for item in data.get("cast", []):
                    media_type = item.get("media_type")
                    item_id = item.get("id")
                    if media_type in ["movie", "tv"] and item_id not in seen_ids:
                        seen_ids.add(item_id)
                        title = item.get("title") if media_type == "movie" else item.get("name")
                        release_date = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
                        results.append(SearchResult(id=item_id, title=title or "Unknown", media_type=media_type, poster_path=get_image_url(item.get("poster_path")), overview=item.get("overview"), release_date=release_date, vote_average=item.get("vote_average")))
            if role in ["all", "director"]:
                for item in data.get("crew", []):
                    if item.get("job") == "Director":
                        media_type = item.get("media_type")
                        item_id = item.get("id")
                        if media_type in ["movie", "tv"] and item_id not in seen_ids:
                            seen_ids.add(item_id)
                            title = item.get("title") if media_type == "movie" else item.get("name")
                            release_date = item.get("release_date") if media_type == "movie" else item.get("first_air_date")
                            results.append(SearchResult(id=item_id, title=title or "Unknown", media_type=media_type, poster_path=get_image_url(item.get("poster_path")), overview=item.get("overview"), release_date=release_date, vote_average=item.get("vote_average")))
            results.sort(key=lambda x: x.release_date or "", reverse=True)
            results = results[:30]
            person_cache.set(cache_key, results)
            return results
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@api_router.get("/providers/{media_type}/{content_id}", response_model=WatchProviderResult)
async def get_watch_providers(media_type: str, content_id: int):
    if not TMDB_API_KEY:
        raise HTTPException(status_code=500, detail="TMDB API key not configured")
    if media_type not in ["movie", "tv"]:
        raise HTTPException(status_code=400, detail="media_type must be 'movie' or 'tv'")
    cache_key = f"providers:{media_type}:{content_id}"
    cached_result = provider_cache.get(cache_key)
    if cached_result is not None:
        return cached_result
    async with httpx.AsyncClient() as http_client:
        try:
            details_response = await http_client.get(f"{TMDB_BASE_URL}/{media_type}/{content_id}", params={"api_key": TMDB_API_KEY, "language": "it-IT"}, timeout=15.0)
            details_response.raise_for_status()
            details = details_response.json()
            title = details.get("title") if media_type == "movie" else details.get("name")
            poster_path = get_image_url(details.get("poster_path"))
            providers_response = await http_client.get(f"{TMDB_BASE_URL}/{media_type}/{content_id}/watch/providers", params={"api_key": TMDB_API_KEY}, timeout=15.0)
            providers_response.raise_for_status()
            providers_data = providers_response.json()
            italy_providers = providers_data.get("results", {}).get("IT", {})
            def parse_providers(providers_list):
                return [StreamingProvider(provider_id=p.get("provider_id"), provider_name=p.get("provider_name"), logo_path=get_image_url(p.get("logo_path"), "w92")) for p in providers_list]
            result = WatchProviderResult(content_id=content_id, content_title=title or "Unknown", media_type=media_type, poster_path=poster_path, flatrate=parse_providers(italy_providers.get("flatrate", [])), rent=parse_providers(italy_providers.get("rent", [])), buy=parse_providers(italy_providers.get("buy", [])), link=italy_providers.get("link"))
            provider_cache.set(cache_key, result)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

app.include_router(api_router)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
logging.basicConfig(level=logging.INFO)
