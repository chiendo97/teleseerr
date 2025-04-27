import logging
import os
import urllib.parse

import httpx
import requests
from langchain.agents import tool
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field, SecretStr
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
OVERSEERR_API_URL = os.getenv("OVERSEERR_API_URL", "")
OVERSEERR_API_KEY = os.getenv("OVERSEERR_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-nano")
IMAGE_TMDB_URL = "https://image.tmdb.org/t/p/w600_and_h900_bestv2"

logging.basicConfig(level=logging.INFO)


@tool
def search_overseerr(query: str, media_type: str):
    """Searches Overseerr for movies or TV shows and checks their request status.

    Args:
        query: The search query (e.g., movie or TV show title).
        media_type: The type of media to search for ('movie' or 'tv').

    Returns:
        A list of search results or an empty list if nothing is found or an error occurs.
        Each result includes title, year, media ID, media type, status ('Available', 'Requested', 'Not Requested'), and poster_url.
    """
    logging.info(f"Searching Overseerr for query: {query}, media_type: {media_type}")

    url = f"{OVERSEERR_API_URL}/search"
    headers = {"X-Api-Key": OVERSEERR_API_KEY, "Content-Type": "application/json"}
    params = {"query": urllib.parse.quote_plus(query)}
    resp = httpx.get(url, headers=headers, params=params)
    if resp.is_success:
        results = resp.json().get("results", [])
        if media_type:
            results = [r for r in results if r.get("mediaType") == media_type]

        processed_results = []
        for r in results[:2]:
            media_info = r.get("mediaInfo")
            status = "Not Requested"
            if media_info:
                # Status codes: 1: Unknown, 2: Pending, 3: Processing, 4: Partially Available, 5: Available
                # We consider 5 as Available, others (2, 3, 4) as Requested/Processing
                media_status = media_info.get("status")
                media_status_4k = media_info.get(
                    "status4k"
                )  # Check 4k status as well if applicable
                if media_status == 5 or media_status_4k == 5:
                    status = "Available"
                elif media_status in [2, 3, 4] or media_status_4k in [2, 3, 4]:
                    status = (
                        "Requested"  # Includes Pending, Processing, Partially Available
                    )

            poster_path = r.get("posterPath")
            poster_url = f"{IMAGE_TMDB_URL}{poster_path}" if poster_path else None

            processed_results.append(
                {
                    "title": r.get("title") or r.get("name"),
                    "year": r.get("releaseDate", "")[:4],
                    "media_id": r.get("id"),
                    "media_type": r.get("mediaType"),
                    "overview": r.get("overview"),
                    "status": status,
                    "poster_url": poster_url,  # Add poster URL
                }
            )

        logging.info(
            f"Overseerr search response: {resp.status_code} - {processed_results}"
        )

        return processed_results
    else:
        logging.error(f"Overseerr search failed: {resp.status_code} - {resp.text}")
        return [resp.text]


# No longer an agent tool, but a regular async function
async def request_overseerr(
    media_id: int, media_type: str, seasons: list[int] | None = None
) -> str:
    """Sends a request to Overseerr to add a movie or TV show, optionally specifying seasons for TV shows.

    Args:
        media_id: The unique ID of the movie or TV show from Overseerr search.
        media_type: The type of media ('movie' or 'tv').
        seasons: An optional list of season numbers to request for TV shows.

    Returns:
        A confirmation message indicating success or failure.
    """
    url = f"{OVERSEERR_API_URL}/request"
    headers = {"X-Api-Key": OVERSEERR_API_KEY, "Content-Type": "application/json"}
    data: dict[str, int | str | list[int]] = {
        "mediaId": media_id,
        "mediaType": media_type,
    }

    # Add seasons to the payload only if it's a TV show and seasons are specified
    if media_type == "tv" and seasons:
        data["seasons"] = seasons
        logging.info(f"Requesting specific seasons for TV show {media_id}: {seasons}")

    resp = requests.post(url, headers=headers, json=data)
    if resp.ok:
        season_text = f" (Seasons: {', '.join(map(str, seasons))})" if seasons else ""
        return f"Successfully requested {media_type} with ID {media_id}{season_text}."
    else:
        logging.error(f"Overseerr request failed: {resp.status_code} - {resp.text}")
        # Try to parse error message from Overseerr
        error_message = f"Status: {resp.status_code}"
        try:
            error_details = resp.json().get("message")
            if error_details:
                error_message = error_details
        except Exception:
            pass  # Keep original error message if parsing fails
        return f"Failed to request {media_type} with ID {media_id}. {error_message}"


# --- Langgraph Agent Setup ---

tools = [search_overseerr]  # Only search tool for the agent


# Define the structured response format using Pydantic
class OverseerrResponse(BaseModel):
    """Structured response from the Overseerr assistant."""

    answer: str = Field(description="The natural language response to the user.")
    action: str | None = Field(
        None,
        description="Set to 'offer_request' if the user should be prompted to request the item.",
    )
    media_id: int | None = Field(
        None,
        description="The media ID to be requested, only if action is 'offer_request'.",
    )
    media_type: str | None = Field(
        None,
        description="The media type ('movie' or 'tv') to be requested, only if action is 'offer_request'.",
    )
    seasons: list[int] | None = Field(
        None,
        description="List of specific season numbers requested by the user (e.g., [1, 3, 5]). Only applicable if media_type is 'tv'. Null or empty if all seasons or it's a movie.",
    )
    poster_url: str | None = Field(
        None,
        description="The URL of the poster image for the media item, if available.",
    )


# System prompt guiding the agent to use the tool and the response schema
system_prompt = (
    "You are a helpful assistant interacting with the Overseerr API. "
    "Your primary function is searching for media (movies or TV shows) using the search_overseerr tool. "
    "Analyze the user's request for media titles, potentially a specific release year, and specific season numbers (e.g., 'show title 2023', 'movie title s03', 'tv show ss5', 'show season 5 and 6'). Extract the title, year (if mentioned), and season numbers (if mentioned for TV shows, recognizing sX, ssX, season X patterns). "
    "Use the search_overseerr tool with the extracted title and media type ('movie' or 'tv'). "
    "Based on the search results from the tool: "
    "If the first search returns no results: Try calling `search_overseerr` exactly one more time. For this second attempt, use a simplified query, focusing only on the core title and removing any year or season specifiers identified in the user's original request. If this second search also returns no results, inform the user that you couldn't find anything matching their query. Set action, media_id, media_type, seasons, and poster_url to null in the response."
    "If results are found (either on the first or second attempt):"
    "   - If the user specified a year in their original request, try to find a result matching that year among the results found. If a match is found, prioritize that result. If no exact year match is found among the results, mention this and proceed with the top result overall."
    "   - Focus on the selected result (year-matched or top result)."
    "   - If the selected result is 'Available' or 'Requested', inform the user of its status (e.g., 'The movie Title (Year) is already available/requested.'). Include the year, an overview, and the poster_url in the response if available. Do not ask to request it again. Set action, media_id, media_type, and seasons to null in the response."
    "   - If the selected result is 'Not Requested':"
    "       - Clearly state the title, year, status, and provide an overview."
    "       - If it's a TV show and the user specified season numbers (e.g., 's5', 'ss3', 'season 3') in their original request, identify these numbers. Ask the user if they want to request *those specific seasons* (e.g., '... Would you like to request season 3 and 5?'). Populate the `seasons` field in the response schema with the identified season numbers (as integers). "
    "       - If it's a movie, or a TV show where the user did *not* specify seasons, ask if they want to request the item (e.g., '... Would you like to request this movie/show?'). Leave the `seasons` field null or empty."
    "       - Crucially, set action='offer_request', and populate media_id, media_type, and poster_url (if available) with the correct values from the search result in the response schema."
    "If multiple results were returned by the tool, mention that you found multiple results and are presenting the most relevant one (either the year-matched one or the top one), then proceed with the logic described above for that result."
    "Do not make up information. Only use the provided search_overseerr tool and its results."
    "Always structure your final response using the OverseerrResponse schema."
)

llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0, api_key=SecretStr(OPENAI_API_KEY))

# Create the agent using create_react_agent and the Pydantic response format
agent_executor = create_react_agent(
    llm,
    tools,
    prompt=SystemMessage(system_prompt),
    response_format=OverseerrResponse,
    # debug=True,
)


# --- Telegram Bot Logic ---


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"Received a message from Telegram bot: {update}.")

    message = update.message or update.channel_post
    if not message:
        return  # No message to process

    text = message.text
    message_id = message.message_id
    user_id = message.chat.id  # Get user ID for sending messages
    chat_id = message.chat_id  # Get chat ID for sending photos

    logging.info(f"Received message from user {user_id}: {text}")

    try:
        # Invoke the agent using the new format
        response = await agent_executor.ainvoke({"messages": [("user", text)]})

        logging.info(f"Agent full response: {response}")

        keyboard = None
        reply_text = (
            "Sorry, I encountered an issue processing your request."  # Default message
        )
        poster_url = None

        # Extract the final answer and structured response
        final_messages = response.get("messages", [])
        if final_messages:
            reply_text = final_messages[-1].content

            # Attempt to get structured response first for more control
            structured_output: OverseerrResponse | None = response.get(
                "structured_response"
            )

            if structured_output:
                poster_url = (
                    structured_output.poster_url
                )  # Get poster URL from structured output

                if structured_output.action == "offer_request":
                    media_id = structured_output.media_id
                    media_type = structured_output.media_type
                    seasons = structured_output.seasons or []  # Get seasons list

                    if media_id and media_type:
                        # Construct callback data, including seasons if present
                        seasons_str = ""
                        if seasons and media_type == "tv":  # Ensure seasons is not None
                            seasons_str = "_" + "-".join(
                                map(str, sorted(seasons))  # Sort requires iterable
                            )  # Format: _1-3-5

                        callback_data = f"request_{media_type}_{media_id}{seasons_str}"

                        # Adjust button text if specific seasons are requested
                        button_text = f"Yes, request this {media_type}"
                        if seasons_str:
                            season_display = ", ".join(map(str, sorted(seasons)))
                            button_text = f"Yes, request season(s) {season_display}"

                        keyboard_buttons = [
                            [
                                InlineKeyboardButton(
                                    button_text,
                                    callback_data=callback_data,
                                )
                            ],
                            [
                                InlineKeyboardButton(
                                    "No, cancel", callback_data="cancel_request"
                                )
                            ],
                        ]
                        keyboard = InlineKeyboardMarkup(keyboard_buttons)
                        logging.info(
                            f"Offering request via structured output for {media_type} ID {media_id}, Seasons: {seasons}"
                        )

        logging.info(f"Final reply text: {reply_text}")
        logging.info(f"Poster URL: {poster_url}")
        logging.info(f"Keyboard: {keyboard}")  # Log the keyboard structure

        # Send the poster image first if available
        if poster_url:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"{reply_text}\n{poster_url}",
                    reply_markup=keyboard,
                    reply_to_message_id=message_id,
                    disable_web_page_preview=False,
                )
            except Exception as img_err:
                logging.error(f"Error sending photo {poster_url}: {img_err}")
                # Fallback to sending text only if photo fails
                await message.reply_text(
                    reply_text, reply_markup=keyboard, reply_to_message_id=message_id
                )
        else:
            # Send the text reply if no poster URL
            await message.reply_text(
                reply_text, reply_markup=keyboard, reply_to_message_id=message_id
            )

    except Exception as e:
        logging.error(f"Error processing message: {e}", exc_info=True)
        await message.reply_text(
            "Sorry, an error occurred while processing your request."
        )


async def button_callback(update: Update, _: ContextTypes.DEFAULT_TYPE):
    """Handles inline button presses."""
    query = update.callback_query
    if not query:
        return  # No callback query to process

    await query.answer()  # Acknowledge the button press

    callback_data = query.data
    logging.info(f"Received callback query with data: {callback_data}")

    if not callback_data:
        return  # No callback data to process

    if callback_data.startswith("request_"):
        try:
            parts = callback_data.split("_")
            media_type = parts[1]
            media_id = int(parts[2])
            seasons = None

            # Check if season information is included (part 4)
            if len(parts) > 3 and media_type == "tv":
                seasons_str = parts[3]
                # Parse seasons formatted as "1-3-5"
                seasons = [int(s) for s in seasons_str.split("-") if s.isdigit()]
                if not seasons:  # Handle case where parsing might fail or be empty
                    seasons = None

            logging.info(
                f"Processing request for {media_type} with ID {media_id}, Seasons: {seasons}"
            )
            # Pass seasons to the request function
            result_message = await request_overseerr(
                media_id, media_type, seasons=seasons
            )
            await query.edit_message_text(text=f"Request result: {result_message}")
        except Exception as e:
            logging.error(f"Error processing request callback: {e}", exc_info=True)
            await query.edit_message_text(
                text="Sorry, there was an error processing your request."
            )
    elif callback_data == "cancel_request":
        await query.edit_message_text(text="Request cancelled.")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()  # type: ignore
    app.add_handler(
        MessageHandler(
            filters.COMMAND,
            handle_message,
        )
    )
    app.add_handler(
        CallbackQueryHandler(button_callback)
    )  # Add handler for button clicks
    app.run_polling()


if __name__ == "__main__":
    main()
