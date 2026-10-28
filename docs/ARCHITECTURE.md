# ToolNet Group Publisher

## Rules
- One Pipeline belongs to exactly one CTV.
- One CTV belongs to exactly one Pipeline.
- Only Admin can create Pipelines and CTV accounts.
- CTV cannot access other Pipeline data.
- Passwords must be securely hashed.
- Modules must remain independently maintainable.

## Backend modules
accounts: Admin, CTV, authentication
pipelines: Pipeline management and isolation
facebook: Facebook accounts
groups: Facebook Group destinations
albums: Image libraries
content: Captions and AI content
scheduler: Publishing schedules
publisher: Posting execution
audit: Activity and security logs

## Frontend
Admin dashboard and CTV workspace.

## Infrastructure
Database, workers, Redis, deployment.
