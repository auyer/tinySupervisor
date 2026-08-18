import os

from tinysupervisor import CronJob, Job, Process, Service, init_supervisor


def render_index(file_names: list[str]) -> str:
    # Generate a <p> tag for each file name using a list comprehension
    lines_list = [
        f'<p><a href="{file_name}">- {file_name}</a></p>' for file_name in file_names
    ]

    # Join the tags with a newline and spaces to maintain HTML indentation
    lines = "\n".join(lines_list)

    # Insert the formatted lines into the base HTML
    base_html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>File List</title>
    </head>
    <body>
        <h1>Files:</h1>
        {lines}
    </body>
    </html>
    """

    return base_html


def write(file_name: str, content: str):
    with open(file_name, "w", encoding="utf-8") as file:
        file.writelines(content)


def index_folder_runner(folder_name):
    files = Process.run(f"ls {folder_name}")
    index = render_index(files)
    Process.run(write, args=["index.html", index])


def server(folder_name):
    port = os.environ.get("TINYSUPERVISOR_SERVICE_PORT", "8080")
    svc = Service.new(command=f"python3 -m http.server {port}", context=folder_name)
    svc.start()


def main():
    supervisor = init_supervisor(
        verbosity=os.environ.get("TINYSUPERVISOR_VERBOSITY", "info")
    )

    supervisor.register(Job(name="init_folder", command="mkdir -p output"))
    supervisor.register(
        CronJob(
            name="index_folder",
            interval="1s",
            executable=index_folder_runner,
            kwargs={"folder_name": "output"},
            depends=["init_folder"],
            dependency_mode="completed",
        )
    )
    supervisor.register(
        Service(
            name="server",
            executable=server,
            kwargs={"folder_name": "output"},
            depends=["init_folder"],
            dependency_mode="completed",
        )
    )

    supervisor.set_heartbeat_interval("1m")  # default reconciler interval

    supervisor.set_http_port(
        int(os.environ.get("TINYSUPERVISOR_HTTP_PORT", "8081"))
    )  # default value

    supervisor.start()


if __name__ == "__main__":
    main()
