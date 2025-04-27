# TeleSeerr - Telegram Bot for Overseerr

## Introduction

TeleSeerr is a Telegram bot that allows users to interact with an Overseerr instance. It uses OpenAI's language models (via Langchain and LangGraph) to understand natural language requests for movies and TV shows, search for them in Overseerr, check their availability status, and offer to request them if they are not already available or requested.

## Requirements

The following environment variables must be set for the bot to function correctly:

*   `TELEGRAM_TOKEN`: Your Telegram Bot Token obtained from BotFather.
*   `OVERSEERR_API_URL`: The base URL of your Overseerr instance API (e.g., `http://your-overseerr-ip:5055/api/v1`).
*   `OVERSEERR_API_KEY`: Your API Key generated within Overseerr settings.
*   `OPENAI_API_KEY`: Your API Key for OpenAI services.
*   `OPENAI_MODEL`: (Optional) The OpenAI model to use (defaults to `gpt-4.1-nano`). You can specify other models like `gpt-4o`, `gpt-4-turbo`, etc.

## Deployment with Docker

You can build and run TeleSeerr using Docker Compose for easier management of environment variables.

1.  **Create a `.env` file:**
    In the project's root directory (where the `Dockerfile` and `docker-compose.yml` are located), create a file named `.env` and add your environment variables:
    ```dotenv
    # .env file
    TELEGRAM_TOKEN="YOUR_TELEGRAM_TOKEN"
    OVERSEERR_API_URL="YOUR_OVERSEERR_API_URL"
    OVERSEERR_API_KEY="YOUR_OVERSEERR_API_KEY"
    OPENAI_API_KEY="YOUR_OPENAI_API_KEY"
    OPENAI_MODEL="gpt-4.1-nano" # Optional, defaults to gpt-4.1-nano
    ```
    Replace the placeholder values with your actual credentials and URLs. **Do not commit this file to version control if it contains sensitive information.** Add `.env` to your `.gitignore` file.

2.  **Create a `docker-compose.yml` file:**
    Create a file named `docker-compose.yml` in the project root directory with the following content (or adapt existing one):
    ```yaml
    # docker-compose.yml
    services:
      teleseerr:
        build: .
        container_name: teleseerr
        env_file:
          - .env
        restart: unless-stopped
    ```

3.  **Build and run with Docker Compose:**
    Navigate to the project directory in your terminal and run:
    ```bash
    docker compose up --build -d
    ```
    *   `--build`: Forces Docker Compose to build the image before starting the container (useful for the first run or after code changes).
    *   `-d`: Runs the container in detached mode (in the background).

    To stop the container, run:
    ```bash
    docker compose down
    ```

## Running Locally

To run the bot locally without Docker:

1.  **Clone the repository (if applicable):**
    ```bash
    git clone <repository-url>
    cd teleseerr
    ```

2.  **Install dependencies:**
    This project uses `uv` for dependency management. Ensure `uv` is installed.
    ```bash
    # Install dependencies using uv
    uv sync
    ```

3.  **Set Environment Variables:**
    Export the required environment variables listed in the [Requirements](#requirements) section.
    ```bash
    export TELEGRAM_TOKEN="YOUR_TELEGRAM_TOKEN"
    export OVERSEERR_API_URL="YOUR_OVERSEERR_API_URL"
    export OVERSEERR_API_KEY="YOUR_OVERSEERR_API_KEY"
    export OPENAI_API_KEY="YOUR_OPENAI_API_KEY"
    # export OPENAI_MODEL="gpt-4.1-nano" # Optional
    ```

4.  **Run the bot:**
    ```bash
    python telegram_bot.py
    ```

## Usage Examples

Interact with the bot in your Telegram chat using the `/request` command followed by your query:

*   **Request a movie:**
    `/request The Matrix`

*   **Request a TV show:**
    `/request The Simpsons`

*   **Request a specific season of a TV show:**
    `/request Game of Thrones s03`
    `/request Stranger Things season 4`

*   **Request multiple specific seasons:**
    `/request The Office s02 and s05`

*   **Specify a year:**
    `/request Dune 2021`

The bot will search Overseerr, report the status, and if the item is not requested, it will offer a button to initiate the request (for specific seasons if mentioned, otherwise the whole show/movie).
