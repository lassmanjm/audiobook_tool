from absl import app
from absl import flags
from absl import logging
import os
import requests
import shutil
import subprocess
import tempfile

FLAGS = flags.FLAGS
flags.DEFINE_string(
    "asin",
    None,
    "Amazon Standard Identification Number. Used to look up metadata from Audible",
    required=True,
)
# flags.DEFINE_string(
#     "input",
#     None,
#     "The path to the input file or directory containing files",
#     required=True,
# )
# flags.DEFINE_string(
#     "output",
#     None,
#     "Amazon Standard Identification Number. Used to look up metadata from Audible",
#     required=True,
# )
flags.DEFINE_bool(
    "merge",
    False,
    "Whether to merge the files found in the input directory into a single m4b file. Can also be used to convert the input file to an m4b file.",
)
flags.DEFINE_alias("m", "merge")
flags.DEFINE_bool(
    "get_chapters",
    True,
    "Whether to get chapter data from Audnexus API. If false, will use the chapter data from the input file.",
)
flags.DEFINE_enum(
    "logging", "error", ["debug", "info", "warning", "error", "fatal"], "Log level."
)
flags.DEFINE_bool(
    "debug", False, "If true, print out all metadata information, and do nothing else."
)
flags.DEFINE_alias("d", "debug")
flags.DEFINE_bool(
    "force", False, "If true, skip confirmation."
)
flags.DEFINE_alias("f", "force")

temp_files = "temp_files"


class GetRequestError(Exception):
    pass


def TryCommand(command: str):
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
        )
        if result.stdout:
            logging.debug(result.stdout)
        if result.stderr:
            logging.info(result.stderr)
    except Exception as e:
        if e.stdout:
            logging.debug(e.stdout)
        if e.stderr:
            logging.error(e.stderr)
        raise


def Get(url):
    api_call = requests.get(url)
    api_json = api_call.json()
    if not api_call.ok:
        raise GetRequestError(
            f"Get request failed: {api_json["statusCode"]}: {api_json["error"]} for url {url}. {api_json["message"]}"
        )
    return api_json


def ProcessChapters(chapters: dict):
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
    return out

def CheckContinue():
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
    book_data = Get(f"{api_url}/books/{asin}")
    metadata["author"] = book_data["authors"][0]["name"]
    metadata["title"] = book_data["title"]
    metadata["year"] = book_data["releaseDate"].split("-")[0]
    hours, minutes = divmod(book_data["runtimeLengthMin"], 60)
    metadata["length"] = f"{hours:02d}:{minutes:02d}"
    metadata["narrators"] = ", ".join([narrator["name"] for narrator in book_data["narrators"]][0:5]) + (", ..." if len(book_data["narrators"]) > 5 else "")
    metadata["publisher"] = book_data["publisherName"]
    logging.info(f"Metadata retrieved: {metadata["title"]}")

    if get_chapters:
        chapters = Get(f"{api_url}/books/{asin}/chapters")
        metadata["chapters"] = ProcessChapters(chapters)
    logging.info("Chapters retrieved.")
    return metadata


def PrintDebug(metadata: dict, get_chapters: bool):
    print(
        f"\nTitle: {metadata["title"]}\nAuthor: {metadata["author"]}\nYear: {metadata["year"]}\nLength: {metadata["length"]}\nNarrators: {metadata["narrators"]}\nPublisher: {metadata["publisher"]}\n"
    )
    if not get_chapters:
        return
    for chapter in metadata["chapters"]:
        print(f"{chapter["hms"]} {chapter["title"]}")


def WriteMetadataFile(metadata: dict, path: str, get_chapters: bool):
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


def MergeFiles(input: str, output: str):
    logging.info(f"Merging files to '{output}'")
    TryCommand(f'm4b-tool merge "{input}" --output-file="{output}"')


def AddMetadataToFile(input, metadata_filepath, get_chapters, output_dir):
    extension = os.path.splitext(input)[1]
    output_filepath = os.path.join(output_dir, f"with_metadata{extension}")
    logging.info(f"Adding metadata to file '{output_filepath}'")
    TryCommand(
        f"ffmpeg -y -i \"{input}\" -i \"{metadata_filepath}\" -map 0:a -map_metadata 1 {"-map_chapters 1 " if get_chapters else ""}-c copy \"{output_filepath}\""
    )
    return output_filepath


def main(argv):
    logging.set_verbosity(FLAGS.logging)
    get_chapters = FLAGS.get_chapters
    asin = FLAGS.asin
    metadata = GetMetadata(asin, get_chapters)
    if FLAGS.debug:
        PrintDebug(metadata, get_chapters)
        return

    input_file = argv[1]
    output_path = argv[2]

    path = os.path.join(output_path, metadata["author"], f"{metadata["title"]} {asin}")

    print("\nFound metadata for:")
    PrintDebug(metadata, get_chapters=False)
    if (FLAGS.merge):
        print("Merging files")
    print(f"Importing {len(metadata["chapters"])} chapters" if get_chapters else "Not importing chapters.")
    print(f"Writing to '{path}'")

    if not FLAGS.force and not CheckContinue():
        return

    os.makedirs(path, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=path) as temp_dir:
        metadata_filepath = WriteMetadataFile(metadata, temp_dir, get_chapters)

        if FLAGS.merge:
            merge_out = os.path.join(temp_dir, "merged.m4b")
            MergeFiles(input_file, merge_out)
            input_file = merge_out
        else:
            if os.path.isdir(input_file):
                raise IsADirectoryError(
                    "The given input is a directory, not a file. If the contents of the directory should be merged, inlcude the --merge flag."
                )
        file_with_metadata = AddMetadataToFile(
            input_file, metadata_filepath, get_chapters, temp_dir
        )
        extension = os.path.splitext(file_with_metadata)[1]
        shutil.move(
            file_with_metadata, os.path.join(path, f"{metadata['title']}{extension}")
        )


if __name__ == "__main__":
    app.run(main)
