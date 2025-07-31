# Swedish Pathogens Portal

WIP repository for Swedish Pathogens Portal 2.0

## Technology Stack

- **Backend**: Django 5.2+
- **Database**: PostgreSQL 17
- **Template Engine**: Django templates
- **CSS Framework**: TailwindCSS
- **JavaScript**: htmx
- **Package Manager**: uv
- **Containerization**: Docker & Docker Compose

## Prerequisites

- Docker and Docker Compose
- Python 3.13+ (for local development)
- uv (for local development)

## Quick Start with Docker

The easiest way to run the project is using Docker Compose. This project uses Docker Compose profiles to manage different environments:

- **`dev`**: Development environment with web application and PostgreSQL database
- **`prod`**: Production environment (to be configured)

For development, we'll use the `dev` profile:

1. **Clone the repository**

   ```bash
   git clone git@github.com:ScilifelabDataCentre/swedish-pathogens-portal.git
   cd swedish-pathogens-portal
   ```

2. **Set up environment variables**
   Create a `.env` file in the root directory with the following variables:

   ```env
   DEBUG=True
   SECRET_KEY=your-secret-key-here
   ALLOWED_HOSTS=localhost,127.0.0.1
   POSTGRES_DB=pathogens_portal
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=your-password
   POSTGRES_HOST=db
   POSTGRES_PORT=5432
   ```

3. **Build and start the services**

   ```bash
   docker-compose --profile dev up --build
   ```

4. **Run database migrations** (in a new terminal)

   ```bash
   docker-compose --profile dev exec web python manage.py migrate
   ```

5. **Create a superuser** (optional)

   ```bash
   docker-compose --profile dev exec web python manage.py createsuperuser
   ```

6. **Access the application**
   - Web application: http://localhost:8000
   - Admin interface: http://localhost:8000/admin

## Local Development

### Using uv (Recommended)

1. **Install uv**

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Set up the environment**

   ```bash
   uv sync
   ```

3. **Set up environment variables** (same as Docker setup)

4. **Run the development server**
   ```bash
   uv run python manage.py runserver
   ```

### Using Devbox

1. **Install devbox**

   ```bash
   curl -fsSL https://get.jetpack.io/devbox | bash
   ```

2. **Enter the development shell**

   ```bash
   devbox shell
   ```

3. **Install dependencies and run**
   ```bash
   uv sync
   python manage.py runserver
   ```

## Project Structure

```
swedish-pathogens-portal/
├── pathogens_portal/          # Main Django project
│   ├── settings.py           # Django settings
│   ├── urls.py              # Main URL configuration
│   └── wsgi.py              # WSGI application
├── pages/                    # Django apps
│   └── home/                # Home page app
├── docker-compose.yml        # Docker Compose configuration
├── Dockerfile               # Docker image definition
├── pyproject.toml           # Project dependencies (uv)
├── requirements.txt          # Legacy requirements (for reference)
└── manage.py                # Django management script
```

## Database

The project uses PostgreSQL as the database. In the Docker setup, PostgreSQL runs in a separate container with health checks to ensure the database is ready before starting the web application.

### Database Configuration

- **Host**: `db` (Docker) or `localhost` (local)
- **Port**: `5432`
- **Database**: `pathogens_portal`
- **User**: `postgres`

## Development Commands

### Docker Commands

```bash
# Start services (with dev profile)
docker-compose --profile dev up

# Start services in background (with dev profile)
docker-compose --profile dev up -d

# Stop services
docker-compose --profile dev down

# View logs
docker-compose --profile dev logs -f web

# Run Django commands
docker-compose --profile dev exec web python manage.py [command]

# Rebuild containers
docker-compose --profile dev build --no-cache
```

### Local Development Commands

```bash
# Install dependencies
uv sync

# Run migrations
uv run python manage.py migrate

# Create superuser
uv run python manage.py createsuperuser

# Run development server
uv run python manage.py runserver

# Run tests
uv run python manage.py test
```

## Environment Variables

The following environment variables are required:

| Variable            | Description                           | Default                             |
| ------------------- | ------------------------------------- | ----------------------------------- |
| `DEBUG`             | Enable debug mode                     | `False`                             |
| `SECRET_KEY`        | Django secret key                     | Required                            |
| `ALLOWED_HOSTS`     | Comma-separated list of allowed hosts | `[]`                                |
| `POSTGRES_DB`       | PostgreSQL database name              | `pathogens_portal`                  |
| `POSTGRES_USER`     | PostgreSQL username                   | `postgres`                          |
| `POSTGRES_PASSWORD` | PostgreSQL password                   | Required                            |
| `POSTGRES_HOST`     | PostgreSQL host                       | `db` (Docker) / `localhost` (local) |
| `POSTGRES_PORT`     | PostgreSQL port                       | `5432`                              |

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `uv run python manage.py test`
5. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
