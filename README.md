# swedish-pathogens-portal

WIP repository for Swedish Pathogens Portal 2.0

## Technology stack

- Django
- PostgreSQL
- Django templates language
- TailwindCSS
- htmx

## How to recreate the development environment

This project is configured to use reproducible and isolated environments for development.
It uses `uv` for python dependencies and environment management.
There are two options:

### Docker

```
docker compose --profile dev up
```

### Devbox 

```
devbox shell
```

Or add `direnv` to your local project directory for automated shell environment switching.