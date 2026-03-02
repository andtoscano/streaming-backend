# E 'ndoe l'è che la se trova? - Backend API

Backend per l'app di ricerca streaming italiano.

## Deploy su Render

1. Carica questo repository su GitHub
2. Vai su render.com e crea "New Web Service"
3. Collega il repository GitHub
4. Aggiungi le Environment Variables:
   - `TMDB_API_KEY` = la tua chiave TMDB
   - `MONGO_URL` = la connection string di MongoDB Atlas
   - `DB_NAME` = streaming_discovery

## API Endpoints

- `GET /api/` - Health check
- `GET /api/search?query=titolo` - Cerca film/serie
- `GET /api/providers/{movie|tv}/{id}` - Ottieni piattaforme streaming
