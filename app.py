import openai
from googleapiclient.discovery import build
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
import json
from dotenv import load_dotenv
import os

# Load environment variables from the .env file
load_dotenv()

# API Keys
OPNEAI_API_KEY = os.getenv('OPNEAI_API_KEY')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

openai.api_key = OPNEAI_API_KEY

# Available languages
languages = {
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Russian": "ru",
    "Chinese": "zh-cn",
    "Italian": "it",
}

# User data storage
user_data = {}

# Fitness levels
fitness_levels = [
    "Unfit and significantly overweight",
    "Unfit",
    "Moderately fit",
    "Fit",
    "Very fit",
]

# Helper function to translate text
def translate_text(text: str, target_lang: str) -> str:
    try:
        # Define the system prompt for translation
        prompt = (
            f"Translate the following text to {target_lang}:\n\n"
            f"{text}"
        )

        # Call OpenAI API
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "system", "content": prompt}],
            temperature=0.2,
        )

        # Extract the translated text
        translated_text = response["choices"][0]["message"]["content"].strip()
        return translated_text

    except Exception as e:
        print(f"Error during translation: {e}")
        return text

# Function to fetch user's language preference
def get_user_language(chat_id: int) -> str:
    return user_data.get(chat_id, {}).get("language", "en")

# Function to fetch videos using YouTube Data API
def fetch_youtube_video(query):
    """Fetch a YouTube video link using the YouTube Data API."""
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    request = youtube.search().list(
        q=query,
        part="snippet",
        maxResults=1,
        type="video"
    )
    response = request.execute()

    # Extract the video link
    if response["items"]:
        video_id = response["items"][0]["id"]["videoId"]
        return f"https://www.youtube.com/watch?v={video_id}"
    else:
        return "No video found for this query."

async def generate_workout_with_youtube(fitness_level: str, duration: int) -> str:
    """Generate a workout plan and fetch valid YouTube links using YouTube Data API."""

    # Prompt for GPT-4
    prompt = f"Create a {duration}-minute workout plan for a person who is {fitness_level.lower()}. Ensure that each exercise includes a valid YouTube query."
    prompt += """Your response must be in valid Array of JSON format, structured as follows:
        [
            {
                "name": "Exercise name",
                "description": "Exercise description",
                "reps": "Number of reps (or duration)",
                "query": "A short query to find a relevant YouTube video"
            }
        ]"""
        
    try:
        # Call the OpenAI API
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        res_json_str = response["choices"][0]["message"]["content"]

        # Parse the JSON response
        try:
            workout_list = json.loads(res_json_str)
            print("====================Res Json Start==========================")
            print(workout_list)
            print("====================Res Json End==========================")

        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {e}")
            return "Error generating workout plan. Please try again."

        # Fetch YouTube links for each exercise
        formatted_workout = []
        for exercise in workout_list:
            query = exercise.get("query", "")

            # Fetch YouTube video link
            video_url = fetch_youtube_video(query) if query else "No video found."

            exercise["video_url"] = video_url
            print("====================video_url Start==========================")
            print(video_url)
            print("====================video_url End==========================")

            formatted_workout.append(exercise)

        return formatted_workout

    except Exception as e:
        print(f"Error generating workout plan: {e}")
        return "An error occurred while generating the workout plan. Please try again later."

# Telegram bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome the user and ask for the language."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_data[chat_id] = {"fitness_level": None, "language": "en"}

    keyboard = [
        [InlineKeyboardButton("English", callback_data="language_English")],
        [InlineKeyboardButton("Spanish", callback_data="language_Spanish")],
        [InlineKeyboardButton("French", callback_data="language_French")],
        [InlineKeyboardButton("German", callback_data="language_German")],
        [InlineKeyboardButton("Russian", callback_data="language_Russian")],
        [InlineKeyboardButton("Chinese", callback_data="language_Chinese")],
        [InlineKeyboardButton("Italian", callback_data="language_Italian")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message = "Please choose your language:"
    await update.message.reply_text(message, reply_markup=reply_markup)

async def language_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Store the language and ask for fitness level."""
    query = update.callback_query
    await query.answer()
    selected_language = query.data.split("_")[1]
    chat_id = query.message.chat_id

    # Store selected language
    user_data[chat_id]["language"] = languages[selected_language]

    # Translate the next question
    fitness_question = translate_text(
        "How would you describe your fitness level?", languages[selected_language]
    )
    reply_markup = InlineKeyboardMarkup.from_column(
        [InlineKeyboardButton(level, callback_data=f"fitness_{level}") for level in fitness_levels]
    )

    await query.edit_message_text(fitness_question, reply_markup=reply_markup)

async def fitness_level_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Store the fitness level."""
    query = update.callback_query
    await query.answer()
    fitness_level = query.data.split("_")[1]
    chat_id = query.message.chat_id

    user_data[chat_id]["fitness_level"] = fitness_level

    # Translate the duration prompt
    user_lang = get_user_language(chat_id)
    duration_question = translate_text(
        "How many minutes (between 2 and 200) would you like the session to last?",
        user_lang,
    )

    await query.edit_message_text(duration_question)

async def session_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle session duration input and generate a workout."""
    chat_id = update.effective_chat.id
    text = update.message.text
    user_lang = get_user_language(chat_id)

    try:
        duration = int(text)
        if 2 <= duration <= 200:
            fitness_level = user_data.get(chat_id, {}).get("fitness_level", "Unfit")
            workout_plans = await generate_workout_with_youtube(fitness_level, duration)

            for exercise in workout_plans:
                name = translate_text(exercise.get("name", "Unknown Exercise"), user_lang)
                description = translate_text(exercise.get("description", "No description provided."), user_lang)
                reps = translate_text(exercise.get("reps", "No reps specified."), user_lang)
                video_url = exercise.get("video_url", "No video found.")

                exercise_message = (
                    f"<b>{name}</b>\n\n"
                    f"<b>Description:</b> {description}\n\n"
                    f"<b>Reps</b>: {reps}\n\n"
                    f'<a href="{video_url}">Video demonstration</a>'
                )

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=exercise_message,
                    parse_mode="html",
                )
        else:
            error_message = translate_text("Please enter a number between 2 and 200.", user_lang)
            await update.message.reply_text(error_message)

    except ValueError:
        error_message = translate_text("Please enter a valid number.", user_lang)
        await update.message.reply_text(error_message)

async def update_preferences(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Allow user to update their preferences."""
    chat_id = update.effective_chat.id
    user_lang = get_user_language(chat_id)

    update_message = translate_text("What would you like to update?", user_lang)
    keyboard = [
        [InlineKeyboardButton(translate_text("Update Language", user_lang), callback_data="update_language")],
        [InlineKeyboardButton(translate_text("Update Fitness Level", user_lang), callback_data="update_fitness")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(update_message, reply_markup=reply_markup)

async def handle_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle specific updates."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user_lang = user_data.get(chat_id, {}).get("language", "English")

    if query.data == "update_language":
        # Translate the language selection prompt
        language_prompt = translate_text(
            "Please choose your new language:", user_lang
        )

        # Show language options
        keyboard = [
            [InlineKeyboardButton("English", callback_data="language_English")],
            [InlineKeyboardButton("Spanish", callback_data="language_Spanish")],
            [InlineKeyboardButton("French", callback_data="language_French")],
            [InlineKeyboardButton("German", callback_data="language_German")],
            [InlineKeyboardButton("Russian", callback_data="language_Russian")],
            [InlineKeyboardButton("Chinese", callback_data="language_Chinese")],
            [InlineKeyboardButton("Italian", callback_data="language_Italian")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(language_prompt, reply_markup=reply_markup)

    elif query.data == "update_fitness":
        # Reuse the fitness level selection flow
        await fitness_level_selected(update, context)

# Main function to run the bot
def main() -> None:
    """Run the bot."""
    application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("update", update_preferences))
    application.add_handler(CallbackQueryHandler(language_selected, pattern="^language_"))
    application.add_handler(CallbackQueryHandler(fitness_level_selected, pattern="^fitness_"))
    application.add_handler(CallbackQueryHandler(handle_update, pattern="^update_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, session_duration))

    application.run_polling()

main()
