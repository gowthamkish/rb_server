# Resume Builder – Python Backend

Python/FastAPI rewrite of the original Node.js/Express server.

## Stack

| Concern               | Node.js (original)  | Python (this)                |
| --------------------- | ------------------- | ---------------------------- |
| Framework             | Express             | FastAPI                      |
| Database ODM          | Mongoose            | Motor (async MongoDB driver) |
| Password hashing      | bcryptjs            | passlib[bcrypt]              |
| JWT                   | jsonwebtoken        | python-jose                  |
| File upload           | multer              | FastAPI `UploadFile`         |
| DOCX text extraction  | mammoth             | python-docx                  |
| DOC → DOCX conversion | libreoffice-convert | subprocess → libreoffice     |

## Project Structure

```
rb_server_py/
├── main.py                  # App entry point (FastAPI + lifespan)
├── requirements.txt
├── Dockerfile
├── .env
└── app/
    ├── config/
    │   └── database.py      # Motor async MongoDB connection
    ├── middleware/
    │   └── auth.py          # JWT auth dependency
    └── routes/
        ├── auth_routes.py   # POST /api/auth/{register,login,logout}
        ├── resume_routes.py # CRUD /api/resumes/
        └── convert_routes.py# POST /api/convert/
```

## Getting Started

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

Copy `.env` and fill in your values:

```
PORT=5000
MONGODB_URI=mongodb+srv://<user>:<pass>@<cluster>/<db>?...
JWT_SECRET=your_jwt_secret_key_change_this_in_production
CLIENT_URL=http://localhost:5173
```

### 4. Run the server

```bash
python main.py
# or with auto-reload during development:
uvicorn main:app --reload --port 5000
```

The server starts on **http://localhost:5000**.  
Interactive API docs are at **http://localhost:5000/docs**.

## API Endpoints

### Auth (`/api/auth`)

| Method | Path        | Body                        | Auth |
| ------ | ----------- | --------------------------- | ---- |
| POST   | `/register` | `{ name, email, password }` | –    |
| POST   | `/login`    | `{ email, password }`       | –    |
| POST   | `/logout`   | –                           | –    |

### Resumes (`/api/resumes`) — all require `Authorization: Bearer <token>`

| Method | Path                        | Description          |
| ------ | --------------------------- | -------------------- |
| POST   | `/`                         | Create resume        |
| GET    | `/`                         | List all resumes     |
| GET    | `/{id}`                     | Get single resume    |
| PUT    | `/{id}`                     | Update resume        |
| DELETE | `/{id}`                     | Delete resume        |
| GET    | `/{id}/download?format=pdf` | Download resume data |

### Convert (`/api/convert`)

| Method | Path | Description                                      |
| ------ | ---- | ------------------------------------------------ |
| POST   | `/`  | Upload `.doc`/`.docx`, returns `{ text: "..." }` |

## Docker

```bash
docker build -t rb_server_py .
docker run -p 5000:5000 --env-file .env rb_server_py
```
