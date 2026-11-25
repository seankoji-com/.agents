#!/usr/bin/env python3
"""Move issues on a repository's linked project board; Python 3.10+ stdlib only."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys

TRANSITIONS = {"start": "In Progress", "pr": "In Review", "done": "Done"}
ROLE_RANK = {"start": 1, "pr": 2, "done": 3}


class Gap(Exception):
    """A board gap that is reported without failing the work."""


def decide(current, transition, names=None):
    """Return the status to set, or None when the issue is already at or past it."""
    names = names or TRANSITIONS
    rank = 0
    for role, name in names.items():
        if (current or "").casefold() == name.casefold():
            rank = max(rank, ROLE_RANK[role])
    if rank >= ROLE_RANK[transition]:
        return None
    return names[transition]


def choose_project(projects, number=None):
    """Pick the repository's linked project without guessing between several."""
    if number is not None:
        for project in projects:
            if project["number"] == number:
                return project
        raise Gap(f"linked project #{number} not found")
    if not projects:
        raise Gap("no linked project")
    if len(projects) > 1:
        names = ", ".join(f"#{p['number']} {p['title']}" for p in projects)
        raise Gap(f"ambiguous linked projects: {names}; pass --project NUMBER")
    return projects[0]


def status_option(fields, target):
    """Resolve the single-select Status field and the option matching target."""
    field = next((f for f in fields
                  if f.get("name", "").casefold() == "status" and "options" in f), None)
    if field is None:
        raise Gap("no single-select Status field")
    option = next((o for o in field["options"]
                   if o["name"].casefold() == target.casefold()), None)
    if option is None:
        names = ", ".join(o["name"] for o in field["options"]) or "none"
        raise Gap(f"missing Status option {target} (have: {names})")
    return field, option


def apply(client, repo, issue_number, transition, operator=None, verified=None,
          project_number=None, dry_run=False, names=None):
    """Perform one transition. Board gaps are recorded, never raised."""
    owner, name = repo
    names = names or TRANSITIONS
    result = {"repo": f"{owner}/{name}", "issue": issue_number, "tracked": False,
              "status": None, "assigned": None, "skipped": None, "notes": [],
              "dry_run": dry_run}
    try:
        project = choose_project(client.repo_projects(owner, name), project_number)
        fields = client.project_fields(project["id"])
        field, option = status_option(fields, names[transition])
        issue = client.issue(owner, name, issue_number)
    except Exception as error:  # Bookkeeping must never fail the main work.
        result["notes"].append(str(error))
        return result
    result["tracked"] = True

    if not issue["assignees"]:
        login = operator or client.operator()
        if login and not login.lower().endswith("[bot]"):
            if dry_run:
                result["assigned"] = login
            else:
                try:
                    client.assign(owner, name, issue_number, login)
                except RuntimeError as error:
                    result["notes"].append(f"assignment failed: {error}")
                else:
                    result["assigned"] = login
        else:
            result["notes"].append("operator unverified; assignment unchanged")

    try:
        item = next((i for i in client.items(project["id"])
                     if i.get("number") == issue_number), None)
        current = item.get("status") if item else None
        target = decide(current, transition, names)
        if target is None:
            result["skipped"] = f"already {current}"
            return result
        item_id = item["id"] if item else None
        if item_id is None and not dry_run:
            item_id = client.add_item(project["id"], issue["id"])
        if not dry_run:
            client.set_status(project["id"], item_id, field["id"], option["id"])
        result["status"] = target
    except Exception as error:  # Bookkeeping must never fail the main work.
        result["notes"].append(f"status update failed: {error}")
    return result


def format_result(result, transition, verified=None):
    """One handoff-ready line for an issue."""
    prefix = f"issue status: {result['repo']}#{result['issue']}"
    if not result["tracked"]:
        return f"{prefix}: untracked ({'; '.join(result['notes'])})"
    parts = []
    if result["status"]:
        parts.append(result["status"] + (" (dry run)" if result["dry_run"] else ""))
    if result["skipped"]:
        parts.append(f"skipped ({result['skipped']})")
    if result["assigned"]:
        parts.append(f"assigned @{result['assigned']}")
    if result["status"] and transition == "done" and verified:
        parts.append(f"verified {verified}")
    if result["notes"]:
        parts.append("; ".join(result["notes"]))
    return f"{prefix}: " + ", ".join(parts)


def _gh(args):
    completed = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail[:300] or "gh failed")
    return completed.stdout


REPO_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    projectsV2(first: 20) { nodes { id number title } }
  }
}
"""

FIELDS_QUERY = """
query($id: ID!) {
  node(id: $id) {
    ... on ProjectV2 {
      fields(first: 50) {
        nodes { ... on ProjectV2SingleSelectField { id name options { id name } } }
      }
    }
  }
}
"""

ISSUE_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      id number
      assignees(first: 20) { nodes { login } }
    }
  }
}
"""

ITEMS_QUERY = """
query($project: ID!, $after: String) {
  node(id: $project) {
    ... on ProjectV2 {
      items(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content { ... on Issue { number } }
          fieldValues(first: 30) {
            nodes {
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2SingleSelectField { name } }
              }
            }
          }
        }
      }
    }
  }
}
"""

CLOSING_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: 50) { nodes { number } }
    }
  }
}
"""

ADD_ITEM_MUTATION = """
mutation($project: ID!, $content: ID!) {
  addProjectV2ItemById(input: {projectId: $project, contentId: $content}) {
    item { id }
  }
}
"""

SET_STATUS_MUTATION = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $project,
    itemId: $item,
    fieldId: $field,
    value: {singleSelectOptionId: $option}
  }) { projectV2Item { id } }
}
"""


class GitHub:
    """Thin gh-backed adapter; each operation is one place a test can replace."""

    def __init__(self, gh=_gh):
        self.gh = gh

    def graphql(self, query, **variables):
        args = ["api", "graphql", "-f", f"query={query}"]
        for key, value in variables.items():
            args += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
        last = None
        for _ in range(2):
            try:
                payload = json.loads(self.gh(args))
                if payload.get("errors"):
                    raise RuntimeError(payload["errors"][0].get("message", "GraphQL error"))
                return payload["data"]
            except (RuntimeError, ValueError) as error:
                last = error
        raise RuntimeError(str(last))

    def repo_projects(self, owner, name):
        data = self.graphql(REPO_QUERY, owner=owner, name=name)
        repository = data.get("repository")
        if repository is None:
            raise Gap("repository not found or not readable")
        return repository["projectsV2"]["nodes"]

    def project_fields(self, project_id):
        data = self.graphql(FIELDS_QUERY, id=project_id)
        node = data.get("node")
        if node is None:
            raise Gap("project not found or not readable")
        return node["fields"]["nodes"]

    def issue(self, owner, name, number):
        data = self.graphql(ISSUE_QUERY, owner=owner, name=name, number=number)
        issue = data["repository"]["issue"]
        if issue is None:
            raise Gap(f"issue #{number} not found")
        return {"id": issue["id"], "number": issue["number"],
                "assignees": [node["login"] for node in issue["assignees"]["nodes"]]}

    def items(self, project_id):
        rows, after = [], None
        while True:
            variables = {"project": project_id}
            if after:
                variables["after"] = after
            node = self.graphql(ITEMS_QUERY, **variables).get("node")
            if node is None:
                raise Gap("project items not readable")
            connection = node["items"]
            for node in connection["nodes"]:
                content = node.get("content") or {}
                if content.get("number") is None:
                    continue
                status = None
                for value in node["fieldValues"]["nodes"]:
                    field = value.get("field") or {}
                    if field.get("name", "").casefold() == "status":
                        status = value.get("name")
                rows.append({"id": node["id"], "number": content["number"], "status": status})
            if not connection["pageInfo"]["hasNextPage"]:
                return rows
            after = connection["pageInfo"]["endCursor"]

    def add_item(self, project_id, content_id):
        data = self.graphql(ADD_ITEM_MUTATION, project=project_id, content=content_id)
        return data["addProjectV2ItemById"]["item"]["id"]

    def set_status(self, project_id, item_id, field_id, option_id):
        self.graphql(SET_STATUS_MUTATION, project=project_id, item=item_id,
                     field=field_id, option=option_id)

    def assign(self, owner, name, number, login):
        self.gh(["api", "--method", "POST", f"repos/{owner}/{name}/issues/{number}/assignees",
                 "-f", f"assignees[]={login}"])

    def project_config(self, owner, name):
        try:
            output = self.gh(["api", f"repos/{owner}/{name}/contents/.github/issue-status.json",
                              "--jq", ".content"])
        except RuntimeError:
            return {}
        try:
            raw = base64.b64decode("".join(output.split())).decode("utf-8")
            config = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise Gap(f"invalid .github/issue-status.json: {error}")
        return config if isinstance(config, dict) else {}

    def operator(self):
        try:
            output = self.gh(["api", "user", "--jq", "[.login, .type] | @tsv"])
        except RuntimeError:
            return None
        login, _, kind = output.strip().partition("\t")
        if not login or kind != "User" or login.lower().endswith("[bot]"):
            return None
        return login

    def closing_issues(self, owner, name, number):
        data = self.graphql(CLOSING_QUERY, owner=owner, name=name, number=number)
        pull = data["repository"]["pullRequest"]
        if pull is None:
            raise Gap(f"PR #{number} not found")
        return [node["number"] for node in pull["closingIssuesReferences"]["nodes"]]


def repository(value):
    owner, _, name = value.partition("/")
    if not owner or not name or "/" in name:
        raise argparse.ArgumentTypeError("use OWNER/REPO")
    return owner, name


def main(argv=None, client=None):
    parser = argparse.ArgumentParser(
        description="Assign the operator and move a linked-project issue status.")
    parser.add_argument("transition", choices=tuple(TRANSITIONS))
    parser.add_argument("--repo", required=True, type=repository, help="OWNER/REPO")
    parser.add_argument("--issue", type=int, action="append", default=[],
                        help="issue number; repeat for several")
    parser.add_argument("--pr", type=int, help="use the PR's closing issues")
    parser.add_argument("--operator", help="verified human login to assign")
    parser.add_argument("--verified", help="deployment or release evidence for done")
    parser.add_argument("--project", type=int, help="linked project number")
    parser.add_argument("--config", help="local option-name mapping JSON")
    parser.add_argument("--dry-run", action="store_true", help="print without changing GitHub")
    args = parser.parse_args(argv)
    if args.transition == "done" and not (args.verified or "").strip():
        parser.error("done requires --verified with the deployment or release evidence")
    if args.pr is not None and args.issue:
        parser.error("use --pr or --issue, not both")
    if args.pr is None and not args.issue:
        parser.error("give --issue (repeatable) or --pr")
    if args.pr is not None and args.transition != "pr":
        parser.error("--pr applies only to the pr transition")

    client = client or GitHub()
    owner, name = args.repo
    try:
        config = (json.loads(Path(args.config).read_text(encoding="utf-8"))
                  if args.config else client.project_config(owner, name))
        if not isinstance(config, dict):
            raise ValueError("config must be a JSON object")
        names = {}
        for role, default in TRANSITIONS.items():
            value = config.get(role, default)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{role} must be a nonempty status name")
            names[role] = value.strip()
        project_number = args.project if args.project is not None else config.get("project")
        if project_number is not None and not isinstance(project_number, int):
            raise ValueError("project must be a number")
    except Exception as error:  # Bookkeeping must never fail the main work.
        print(f"issue status: {owner}/{name}: untracked (invalid issue-status config: {error})")
        return 0
    if args.pr is not None:
        try:
            numbers = client.closing_issues(owner, name, args.pr)
        except Exception as error:  # Bookkeeping must never fail the main work.
            print(f"issue status: {owner}/{name} PR #{args.pr}: untracked ({error})")
            return 0
        if not numbers:
            print(f"issue status: {owner}/{name} PR #{args.pr}: untracked (closes no issues)")
            return 0
    else:
        numbers = args.issue
    for number in numbers:
        result = apply(client, args.repo, number, args.transition,
                       operator=args.operator, verified=args.verified,
                       project_number=project_number, dry_run=args.dry_run, names=names)
        print(format_result(result, args.transition, args.verified))
    return 0


if __name__ == "__main__":
    sys.exit(main())
