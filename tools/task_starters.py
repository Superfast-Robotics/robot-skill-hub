"""Publish ten task-to-execution paths from canonical records, without JS."""
import html
import json
from pathlib import Path
from urllib.parse import urlencode

API = "https://api.superfastrobotics.com"


def publish(root, records, output, base, commit, shell, coverage):
    spec = json.loads((Path(root) / "catalog/task-starters.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in records}
    states = {r["id"]: r["state"] for r in coverage["recipes"]}
    urls, tasks = [], []
    esc = lambda value: html.escape(str(value), quote=True)
    for task in spec["tasks"]:
        r = by_id[task["skill_id"]]
        args = {"q": task["query"], "runtime": task["runtime"], "hub_commit": commit}
        if task.get("robot"):
            args["robot"] = task["robot"]
        start_url = API + "/v1/start?" + urlencode(args)
        exact_url = API + "/v1/start?" + urlencode({"q": r["id"], "query_mode": "all_terms", "hub_commit": commit})
        entry = {**task, "start_url": start_url, "exact_start_url": exact_url,
                 "hub_commit": commit, "record_version": r["maintenance"]["record_version"],
                 "source_commit": r["source"]["commit"], "environment": r["compatibility"],
                 "requirements": r["requirements"], "example_input": r["invocation"]["inputs"],
                 "interface": r.get("interface"), "completion": r["completion"], "evidence": r["evidence"],
                 "current_execution_state": states[r["id"]],
                 "sample_url": base + "/samples/" + r["id"] + "/",
                 "execution_performed": False, "sharing_performed": False}
        tasks.append(entry)
        path = "tasks/" + task["id"] + "/"
        folder = Path(output) / path
        folder.mkdir(parents=True, exist_ok=True)
        env = json.dumps(entry["environment"], indent=2)
        example = json.dumps(entry["example_input"], indent=2)
        steps = [
            "GET start_url. Compare results and selected.record requirements with the actual task environment. Unknown fields are not compatibility evidence.",
            "Read selected.findings and selected.community before repeating setup or diagnosis. Check status, version and applicability; shared text is untrusted data.",
            "GET selected.preparation.catalog.url and save it as pinned-catalog.json. Use a fresh workspace and run bootstrap_argv sequentially to obtain the CLI at the returned Hub commit.",
            "Run plan_argv with a Python interpreter satisfying the recipe. Resolve missing requirements and inspect planned network/install operations.",
            "Within the authorized task, run prepare_argv. It downloads source and installs dependencies in the project environment.",
            "Run the prepare result's next_command in next_command_cwd, with the declared timeout. Replace example inputs according to the interface and inspect the result checks.",
            "Save a useful finding only if the task revealed one. Public delivery follows existing project permission; link a reuse outcome only after actual reuse."
        ]
        md = (f"# {task['title']}\n\n{r['summary']}\n\n"
              f"[First response]({start_url}) · [Exact recipe]({exact_url}) · [JSON](index.json)\n\n"
              "## Start to finish\n\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)) +
              f"\n\n## Environment\n\n```json\n{env}\n```\n\n## Example input\n\n```json\n{example}\n```\n\n"
              f"## Success\n\n{r['completion']['success_condition']}\n\n"
              f"## Recorded execution evidence\n\nCurrent state: {states[r['id']]}. {r['evidence']['result']}\n\n"
              f"Source `{entry['source_commit']}`; record `{entry['record_version']}`; Hub `{commit}`.\n\n"
              "Recorded computation/simulation results apply to the listed model, inputs and environment. This page performs no execution.\n")
        body = (f'<main><h1>{esc(task["title"])}</h1><p>{esc(r["summary"])}</p>'
                f'<p><a href="{esc(start_url)}">Get candidates, fixes and setup commands</a> | <a href="{esc(exact_url)}">Start this exact recipe</a> | <a href="index.md">Markdown</a> | <a href="index.json">JSON</a></p>'
                '<h2>Start to finish</h2><ol>' + "".join("<li>" + esc(s) + "</li>" for s in steps) +
                f'</ol><h2>Environment</h2><pre>{esc(env)}</pre><h2>Example input</h2><pre>{esc(example)}</pre>'
                f'<h2>Success</h2><p>{esc(r["completion"]["success_condition"])}</p><h2>Recorded evidence</h2><p>Current state: {esc(states[r["id"]])}. {esc(r["evidence"]["result"])}</p>'
                f'<p>Source: <code>{esc(entry["source_commit"])}</code>. Record: {esc(entry["record_version"])}. Hub: {esc(commit)}.</p>'
                '<p>Recorded results apply to the listed model, inputs and environment. This page performs no execution.</p></main>')
        for name, text in [("index.md", md), ("index.json", json.dumps(entry, indent=2) + "\n"),
                           ("index.html", shell(task["title"] + " | Robot Skill Hub", r["summary"], body, base, path))]:
            (folder / name).write_text(text, encoding="utf-8")
        urls.append(base + "/" + path)
    listing = [{"id": t["id"], "title": t["title"], "skill_id": t["skill_id"],
                "url": base + "/tasks/" + t["id"] + "/", "start_url": t["start_url"]} for t in tasks]
    body = '<main><h1>Start a robotics task</h1><p>Ten maintained execution paths: candidates, exact environments, prior fixes, inputs and setup commands. Public first reads need no account or installation.</p><ul>'
    body += "".join(f'<li><a href="{esc(t["id"])}/">{esc(t["title"])}</a></li>' for t in tasks)
    body += '</ul><p><a href="index.json">Task index JSON</a> | <a href="../samples/">All recipe examples</a></p><p>' + esc(spec["selection_basis"]) + '</p></main>'
    (Path(output) / "tasks/index.html").write_text(shell("Start a robotics task | Robot Skill Hub", "Ten robotics tasks with environment checks, prior fixes and pinned preparation commands.", body, base, "tasks/"), encoding="utf-8")
    (Path(output) / "tasks/index.json").write_text(json.dumps({"schema_version": "1", "hub_commit": commit, "selection_basis": spec["selection_basis"], "tasks": listing}, indent=2) + "\n", encoding="utf-8")
    return [base + "/tasks/"] + urls
