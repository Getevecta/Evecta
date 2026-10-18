<<<<<<< Updated upstream
# LeadZen
=======
# LeadZen (Evecta)

**Developer documentation:** see [docs/README.md](./docs/README.md) for frontend architecture, API map, design system, and operations.

---

for backend
1.  add .env file 
2. python -m venv env
3.  .\env\Scripts\Activate
4. uvicorn app.main:app --reload
5. celery -A app.core.celery_app.celery_app beat -l info
6. celery -A app.core.celery_app worker -P threads -c 4 --loglevel=info


for frontend
1. npm install 
2. npm run dev 
or 
npm run build 
>>>>>>> Stashed changes
