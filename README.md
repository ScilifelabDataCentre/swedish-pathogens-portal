# Swedish Pathogens Portal

WIP repository for Swedish Pathogens Portal 2.0

## Technology Stack

- **Backend**: Django
- **Database**: PostgreSQL
- **Template Engine**: Django templates
- **CSS Framework**: TailwindCSS
- **JavaScript**: htmx
- **Package Manager**: uv
- **Containerization**: Docker & Docker Compose

## Prerequisites

- Docker and Docker Compose
- Python 3.13+ (for local development)
- uv (for local development) |

## Contributing

You should have `git` and `docker` installed before running the folowwing steps.

#### Clone the repository

Open a terminal window, go to the directory where you want to clone the repository and run

```
git clone git@github.com:ScilifelabDataCentre/swedish-pathogens-portal.git
```

#### Create env file

We need a `.env` file for the application, for local development we can just make a copy of `.env.example`

```
cp .env.example .env
```

#### Start the application

Go into the cloned repository and run the below command.

```
docker compose up
```

If the command ran successfully, open a browser and visit `http://localhost:8000`.

#### To clear old container/images

Sometimes we may have remove the containers, images and start a fresh. 

```
docker compose down --rmi
```

#### Run migrations

To check and test pages which pull data from the DB, django `migrate` should be run

```
docker compose exec web python manage.py migrate
```

#### Make migrations

For new apps and models, one might have to make the migrations files first

```
docker compose exec web python manage.py makemigrations
```

#### Creating new app

To create new app (section), first create a directory with the desired app/section name.

```
docker compose exec web mkdir pages/<app_name>
```

Then use django's utility command to create a app and required files

```
docker compose exec web python manage.py startapp <app_name> pages/<app_name>
```

After creating the app, following steps should be done

- add `pages.<app_name>` to `core/settings/base.py` *installed_apps* list
- rename app name to `pages.<app_name>` in `pages/<app_name>/app.py`
- create `pages/<app_name>/urls.py` file for the app's urls
- then include the apps url in `core/urls.py` (like other apps)
- if needed, create `templates/<app_name>` directory within the app directory for templates
- if needed, create `static/<app_name>` directory within the app directory for static files

#### Modifying dependenices with UV

While developing, to add or remove dependency run

```
docker compose exec web uv <add/remove> <package_name>
```

to add/remove dependency for development

```
docker compose exec web uv <add/remove> --group dev <package_name>
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
