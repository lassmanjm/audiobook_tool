from absl import logging
import os
import requests
import shutil
import subprocess
import tempfile


class GetRequestError(Exception):
    pass


def try_command(command: str):
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        logging.debug(result.stdout)
    if result.stderr:
        logging.info(result.stderr)
    if result.returncode != 0:
        logging.error(result.stderr)
        raise RuntimeError(
            f"Command '{command}' failed with exit code {result.returncode}"
        )


def get(url):
    api_call = requests.get(url)
    api_json = api_call.json()
    if not api_call.ok:
        logging.error(
            f"Get request failed: {api_json['statusCode']}: {api_json['error']} for url {url}. {api_json['message']}"
        )
        raise GetRequestError(
            f"Get request failed: {api_json["statusCode"]}: {api_json["error"]} for url {url}. {api_json["message"]}"
        )
    return api_json


def process_chapters(chapters: dict):
    out = []
    for chapter in chapters["chapters"]:
        start_offset_ms = chapter["startOffsetMs"]
        seconds, milliseconds = divmod(start_offset_ms, 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        out.append(
            {
                "start": start_offset_ms,
                "end": start_offset_ms + chapter["lengthMs"] - 1,
                "title": chapter["title"],
                "hms": f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}",
            }
        )
    logging.debug(f"Processed {len(out)} chapters")
    return out


def check_continue():
    while True:
        selection = input("\nContinue? [y|n]: ").lower()
        if selection == "n":
            print("Exiting...")
            return False
        if selection == "y":
            return True
        elif selection != "y":
            print("Please enter 'y' or 'n'.")


def GetMetadata(asin: str, get_chapters: bool = True) -> dict:
    logging.info("Retrieving metadata...")
    api_url = "https://api.audnex.us"
    metadata = {}
    book_data = get(f"{api_url}/books/{asin}")
    metadata["author"] = book_data["authors"][0]["name"]
    metadata["title"] = book_data["title"]
    metadata["year"] = book_data["releaseDate"].split("-")[0]
    hours, minutes = divmod(book_data["runtimeLengthMin"], 60)
    metadata["length"] = f"{hours:02d}:{minutes:02d}"
    metadata["narrators"] = ", ".join(
        [narrator["name"] for narrator in book_data["narrators"]][0:5]
    ) + (", ..." if len(book_data["narrators"]) > 5 else "")
    metadata["publisher"] = book_data["publisherName"]
    logging.info(f"Metadata retrieved: {metadata["title"]}")

    if get_chapters:
        chapters = get(f"{api_url}/books/{asin}/chapters")
        metadata["chapters"] = process_chapters(chapters)
    logging.info("Chapters retrieved.")
    return metadata


def debug_string(metadata: dict, get_chapters: bool):
    out = (
        f"\nTitle: {metadata["title"]}\nAuthor: "
        f"{metadata["author"]}\nYear: {metadata["year"]}\n"
        f"Length: {metadata["length"]}\nNarrators: "
        f"{metadata["narrators"]}\nPublisher: {metadata["publisher"]}\n"
    )
    if not get_chapters:
        return out
    for chapter in metadata["chapters"]:
        out += f"{chapter['hms']} {chapter['title']}\n"
    return out


def print_debug(metadata: dict, get_chapters: bool, log: bool):
    debug_str = debug_string(metadata, get_chapters)
    if log:
        logging.info(debug_str)
    else:        
        print(debug_str)


def write_metadata_file(metadata: dict, path: str, get_chapters: bool):
    metadata_filepath = os.path.join(path, "metadata.txt")
    logging.info(f"Writing metadata file to '{metadata_filepath}'")
    out = f";FFMETADATA1\nalbum={metadata["title"]}\nalbum_artist={metadata['author']}\nartist={metadata['author']}\nyear={metadata['year']}"
    if get_chapters:
        for chapter in metadata["chapters"]:
            out += f"\n\n[CHAPTER]\nTIMEBASE=1/1000\nSTART={chapter["start"]}\nEND={chapter["end"]}\ntitle={chapter["title"]} "
    with open(metadata_filepath, "w") as f:
        f.write(out)
    logging.info("Metadata file written")
    return metadata_filepath


def merge_files(input: str, temp_dir: str) -> str:
    # Get list of input files and save to temp file
    files = []
    if os.path.isfile(input):
        files.append(os.path.abspath(input))
    for file in sorted(os.listdir(input), key=str.lower):
        if os.path.splitext(file)[1] in {".m4a", ".m4b", ".mp3", ".flac"}:
            files.append(os.path.abspath(os.path.join(input, file)))
    input_list = ""
    for file in files:
        input_list += f"file '{file}'\n"
    merged_input_list = os.path.join(temp_dir, "merge_input_list.txt")
    with open(merged_input_list, "w") as f:
        f.write(input_list)
    # Merge using ffmpeg
    output = os.path.join(temp_dir, "merged.m4b")
    logging.info(f"Merging files to '{output}'")
    try_command(
        f'ffmpeg -f concat -safe 0 -i "{merged_input_list}"  -c:a libfdk_aac -vbr 4 -vn  -y "{output}"'
    )
    return output


def add_metadata_to_file(input, metadata_filepath, get_chapters, output_dir):
    extension = os.path.splitext(input)[1]
    output_filepath = os.path.join(output_dir, f"with_metadata{extension}")
    logging.info(f"Adding metadata to file '{output_filepath}'")
    try_command(
        f'ffmpeg -y -i "{input}" -i "{metadata_filepath}" -map 0:a -map_metadata 1 {"-map_chapters 1 " if get_chapters else ""}-c copy "{output_filepath}"'
    )
    return output_filepath


def process_audiobook(
    input_path: str,
    output_path: str,
    asin: str,
    get_chapters: bool = True,
    debug: bool = False,
    merge: bool = False,
    force: bool = False,
):
    metadata = GetMetadata(asin, get_chapters)
    # return metadata
    if debug:
        print_debug(metadata, get_chapters)
        return
    path = os.path.join(output_path, metadata["author"], f"{metadata["title"]} {asin}")

    logging.info("Found metadata for:")
    print_debug(metadata, get_chapters=False, log=True)
    if merge:
        logging.info("Merging files")
    logging.info(
        f"Importing {len(metadata["chapters"])} chapters"
        if get_chapters
        else "Not importing chapters."
    )
    logging.info(f"Writing to '{path}'")

    if not force and not check_continue():
        return

    os.makedirs(path, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=path) as temp_dir:
        metadata_filepath = write_metadata_file(metadata, temp_dir, get_chapters)

        if merge:
            input_path = merge_files(input_path, temp_dir)
        else:
            if os.path.isdir(input_path):
                raise IsADirectoryError(
                    "The given input is a directory, not a file. If the contents of the directory should be merged, inlcude the --merge flag."
                )
        file_with_metadata = add_metadata_to_file(
            input_path, metadata_filepath, get_chapters, temp_dir
        )
        extension = os.path.splitext(file_with_metadata)[1]
        shutil.move(
            file_with_metadata, os.path.join(path, f"{metadata['title']}{extension}")
        )