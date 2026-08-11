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
    supervisor = init_supervisor()
    # define task dependency each register task should depende of the previous,
    # they should only need them to start, not complete
    supervisor.auto_dependency_mode(mode="register_order", wait_for="start")

    supervisor.register(Job(name="init_folder", executable="mkdir output", args=[]))
    supervisor.register(
        CronJob(
            name="index_folder",
            interval="1m",
            executable=index_folder_runner,
            args=[],
            kwargs={"folder_name": "output"},
        )
    )
    supervisor.register(server, kwargs={"folder_name": "output"})

    supervisor.set_heartbeat_interval("1m")  # default reconciler interval

    supervisor.set_http_port(
        int(os.environ.get("TINYSUPERVISOR_HTTP_PORT", "8081"))
    )  # default value
    # will serve these endpoints:
    # /health
    # /healthz
    # -> return status 200 if OK, 400 if any process is not in its desired state
    #    bory returns state of each process in json:
    #       {"processes":[
    #       {"a": {"current": "running", "desired": "running"}},
    #       {"b": {"current": "sleeping", "desired": "sleeping"}},
    #       {"c": {"current": "stopped", "desired": "stopped"}},
    #       ]}
    #

    supervisor.start()


if __name__ == "__main__":
    main()
