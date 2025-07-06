from typing import Optional
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from mutagen.wave import WAVE
from aiogram.types import Message, LabeledPrice, PreCheckoutQuery
import os
from aiogram.filters import CommandStart, Command
from pydub import AudioSegment
from pydub.silence import detect_nonsilent
import logging
import app.keyboards as kb
from audio_extract import extract_audio

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
    "🎤 Добро пожаловать в бота для транскрибации аудио!\n\n"
    "Просто отправьте аудиофайл или голосовое сообщение, и я переведу его в текст.\n"
    "Первая транскрибация — бесплатно!\n\n"
    "Стоимость: X за минуту аудио",
    parse_mode="Markdown",
    reply_markup=kb.main
)

#А НУЖЕН ЛИ ХЕЛП?
@router.message(Command('help'))
async def cmd_help(message: Message):
    await message.answer('Руководство по командам бота:')

@router.message(F.text == 'Выгрузить аудио')
async def cmd_audio(message: Message):
    await message.answer('Пожалуйста, отправьте ваш файл')


# ОБРАБОТЧИК ГС
@router.message(F.voice)
async def handle_voice(message: Message):
    file_id = message.voice.file_id
    await process_audio(message, file_id, "voice")

# ОБРАБОТЧИК АУДИО
@router.message(F.audio)
async def handle_audio(message: Message):
    file_id = message.audio.file_id
    await process_audio(message, file_id, "audio")

# ОБРАБОТЧИК ВИДЕО
@router.message(F.content_type == "video")
async def handle_video(message: Message):
    logging.basicConfig(level=logging.INFO)
    file_id = message.video.file_id
    file_size = message.video.file_size
    logging.info(f"Размер файла: {file_size}")
    max_size = 20 * 1024 * 1024
    if file_size < max_size:
        await process_video(message, file_id, "video")
    else:
        await message.reply("Файл слишком большой, максимальный размер 20МБ, отправьте другой файл")

# ОБРАБОТЧИК КРУЖОЧКОВ В ТГ
@router.message(F.content_type == "video_note")
async def handle_video(message: Message):
    file_id = message.video_note.file_id
    await process_video(message, file_id, "video_note")

# ОБРАБОТЧИК ФАЙЛОВ НЕ ЯВЛЯЮЩИХСЯ АУДИО ИЛИ ГС 
@router.message(F.photo | F.document)
async def handle_another_files(message: Message):
    await message.answer("Файл не является аудио или голосовым сообщением")

async def process_video(message: Message, file_id: str, file_type: str):
    logging.basicConfig(level=logging.INFO)
    bot = message.bot
    file = await bot.get_file(file_id)
    file_path = file.file_path

    if not os.path.exists('videos'):
        os.makedirs('videos')
        logging.info("Создана директория для видео")
        
    file_format = get_video_format(file_path)
    if not file_format:
        logging.error(f"Данный формат видео не поддерживается: {file_path}")
        message.reply("Данный формат файла не поддерживается. Отправьте другой файл")
        
    file_name = f"{file_type}_{message.from_user.id}_{file_id[:8]}{file_format}"
    save_path = os.path.join("videos", file_name)

    await bot.download_file(file_path, destination=save_path)
    logging.info("Скачан видео файл")

    if not os.path.exists("audios"):
        os.makedirs('audios')
        logging.info("Создана директрия для звуковых дорожек взятых из видео")
        
    audio_file_name = f"audios/audio_{message.from_user.id}_{file_id[:8]}.wav"
    extract_audio(f"videos/{file_name}", audio_file_name, output_format="wav")

    if not await has_audio(audio_file_name):
        logging.error(f"Файл не содержит звука или битый")
        await message.answer('Файл тихий или битый, загрузите качественный аудио файл')
        os.remove(save_path)
        os.remove(audio_file_name)
        return
        
    audio = WAVE(audio_file_name)
    duration = audio.info.length
    logging.info(f"Получена длина аудио дорожки: {duration:.2f}")
    await print_price(int(duration), message)



def get_video_format(file_path: str) -> Optional[str]:
    formats = [".webm", ".mp4", ".mov", ".avi", ".mkv"]
    for fmt in formats:
        if file_path.endswith(fmt):
            return fmt
    return None

async def process_audio(message: Message, file_id: str, file_type: str):
    logging.basicConfig(level=logging.INFO)
    try:
        # ИНФОРМАЦИЯ О ФАЙЛЕ
        bot = message.bot
        file = await bot.get_file(file_id)
        file_path = file.file_path    

        # ИМЯ ФАЙЛА
        file_name = f"{file_type}_{message.from_user.id}_{file_id[:8]}.ogg"
        save_path = os.path.join("downloads", file_name)


        await bot.download_file(file_path, destination=save_path)
        logging.info(f"Файл сохранен: {save_path}")

        # ПРОВЕРКА НА ЗВУК В ФАЙЛЕ
        if not await has_audio(save_path):
            logging.error(f"Файл не содержит звука или битый")
            await message.answer('Файл тихий или битый, загрузите качественный аудио файл')
            os.remove(save_path)
            return
        
        duration = message.voice.duration if file_type == "voice" else message.audio.duration
        await print_price(duration, message)
    except Exception as e:
        logging.error(f"Error: {str(e)}")

async def print_price(duration: int, message: Message):
    cost = calculate_cost(duration)  # СТОИМОСТЬ
    prices = [LabeledPrice(label="XTR", amount=cost)] 
    await message.answer(
        f"✅ Файл получен!\n"
        f"Длительность: {duration // 60}:{duration % 60:02d} мин.\n"
        f"Стоимость: {cost} XTR")

    await message.answer_invoice(
        title="Оплата транскрибации",
        description=f"Сумма: {cost} XTR",
        prices=prices,
        provider_token="",
        payload="trancrib_payment",
        currency="XTR",
        reply_markup=kb.payment_keyboard(cost), 
    )

async def has_audio(audio_path: str, silence_thresh=-50.0, min_silence_len=1000) -> bool:
    audio = AudioSegment.from_file(audio_path)
    nonsilent_ranges = detect_nonsilent(
        audio, 
        min_silence_len=min_silence_len, 
        silence_thresh=silence_thresh
    )
    return len(nonsilent_ranges) > 0

from aiogram.types import PreCheckoutQuery

@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):  
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def success_payment_handler(message: Message):  
    await message.answer(text="Спасибо за вашу оплату!🤗")


def calculate_cost(duration_sec: int) -> float:
    cost_per_minute = 1 # ЗВЁЗДЫ
    minutes = max(1, (duration_sec + 59) // 60)  # Округление вверх
    return minutes * cost_per_minute
#ТРАНСКРИБАЦИЯ
