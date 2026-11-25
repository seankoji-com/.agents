#!/usr/bin/env python3
"""Move issues on a repository's linked project board; Python 3.10+ stdlib only."""
import argparse
import base64
import json
from pathlib import Path
import re
import subprocess
import sys

TRANSITIONS = {"start": "In Progress", "pr": "In Review", "done": "Done"}
ROLE_RANK = {"start": 1, "pr": 2, "done": 3}
# Names a closed or released item may already carry when no mapping is configured.
TERMINAL = {"released": 2, "closed": 2, "shipped": 2}


class Gap(Exception):
    """A board gap that is reported without failing the work."""


def decide(current, transition, names=None):
    """Return the status to set, or None when the issue is already at or past it."""
    names = names or TRANSITIONS
    rank = TERMINAL.get((current or "").casefold(), 0)
    # Standard names stay protected even when a board renames another role.
    for mapping in (TRANSITIONS, names):
        for role, name in mapping.items():
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


def assign_start(client, repo, issue_number, issue, operator=None, dry_run=False):
    """Assign the verified operator once; return (login or None, notes)."""
    owner, name = repo
    notes = []
    if issue["assignees"]:
        return None, notes
    login = operator or client.operator()
    if not login or login.lower().endswith("[bot]"):
        notes.append("operator unverified; assignment unchanged")
        return None, notes
    if dry_run:
        return login, notes
    confirmed = client.assign(owner, name, issue_number, login)
    if login in confirmed:
        return login, notes
    notes.append(f"assignment not confirmed for @{login}")
    return None, notes


def apply(client, repo, issue_number, transition, operator=None, verified=None,
          project_number=None, dry_run=False, names=None):
    """Perform one transition. Board gaps are recorded, never raised."""
    owner, name = repo
    names = names or TRANSITIONS
    result = {"repo": f"{owner}/{name}", "issue": issue_number, "tracked": False,
              "status": None, "assigned": None, "skipped": None, "notes": [],
              "dry_run": dry_run, "failed": False}
    try:
        issue = client.issue(owner, name, issue_number)
    except Exception as error:  # Bookkeeping must never fail the main work.
        result["notes"].append(str(error))
        return result

    # Assignment belongs to the start of work and never needs a board.
    if transition == "start":
        try:
            result["assigned"], notes = assign_start(
                client, repo, issue_number, issue, operator, dry_run)
            result["notes"].extend(notes)
        except Exception as error:  # Bookkeeping must never fail the main work.
            result["notes"].append(f"assignment failed: {error}")

    try:
        project = choose_project(client.repo_projects(owner, name), project_number)
        fields = client.project_fields(project["id"])
        field, option = status_option(fields, names[transition])
    except Exception as error:  # Bookkeeping must never fail the main work.
        result["notes"].append(str(error))
        return result
    result["tracked"] = True

    try:
        item = next((i for i in client.items(project["id"])
                     if i.get("issue_id") == issue["id"]), None)
        current = item.get("status") if item else None
        target = decide(current, transition, names)
        if target is None:
            result["skipped"] = f"already {current}"
            return result
        item_id = item["id"] if item else None
        if item_id is None and not dry_run:
            item_id = client.add_item(project["id"], issue["id"])
        if dry_run:
            result["status"] = target
            return result
        # Re-read immediately before writing. add_item can return an item another
        # writer just created, so a new item is checked too. External writers can
        # still race between this read and the write.
        fresh = client.item_status(item_id)
        target = decide(fresh, transition, names)
        if target is None:
            result["skipped"] = f"changed to {fresh}" if fresh != current else f"already {fresh}"
            return result
        client.set_status(project["id"], item_id, field["id"], option["id"])
        result["status"] = target
    except Exception as error:  # Bookkeeping must never fail the main work.
        result["failed"] = True
        result["notes"].append(f"status update failed: {error}")
    return result


def format_result(result, transition, verified=None):
    """One handoff-ready line for an issue."""
    prefix = f"issue status: {result['repo']}#{result['issue']}"
    assignment = f", assigned @{result['assigned']}" if result["assigned"] else ""
    if not result["tracked"] or result["failed"]:
        notes = "; ".join(result["notes"]) or "unknown gap"
        return f"{prefix}: untracked ({notes}){assignment}"
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
    try:
        completed = subprocess.run(["gh", *args], capture_output=True, text=True,
                                   check=False, timeout=60)
    except OSError as error:
        raise RuntimeError(f"gh unavailable: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("gh timed out") from error
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail[:300] or "gh failed")
    return completed.stdout


REPO_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    projectsV2(first: 20, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { id number title }
    }
  }
}
"""

FIELDS_QUERY = """
query($id: ID!, $after: String) {
  node(id: $id) {
    ... on ProjectV2 {
      fields(first: 50, after: $after) {
        pageInfo { hasNextPage endCursor }
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
          content { ... on Issue { id number } }
          fieldValueByName(name: "Status") {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
        }
      }
    }
  }
}
"""

ITEM_QUERY = """
query($id: ID!) {
  node(id: $id) {
    ... on ProjectV2Item {
      fieldValueByName(name: "Status") {
        ... on ProjectV2ItemFieldSingleSelectValue { name }
      }
    }
  }
}
"""

CLOSING_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      closingIssuesReferences(first: 50, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { number repository { nameWithOwner } }
      }
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

    def graphql(self, query, retry=True, **variables):
        args = ["api", "graphql", "-f", f"query={query}"]
        for key, value in variables.items():
            args += ["-F" if isinstance(value, int) else "-f", f"{key}={value}"]
        last = None
        for _ in range(2 if retry else 1):
            try:
                payload = json.loads(self.gh(args))
                if payload.get("errors"):
                    raise RuntimeError(payload["errors"][0].get("message", "GraphQL error"))
                return payload["data"]
            except (RuntimeError, ValueError) as error:
                last = error
        raise RuntimeError(str(last))

    def repo_projects(self, owner, name):
        rows, after = [], None
        while True:
            variables = {"owner": owner, "name": name}
            if after:
                variables["after"] = after
            data = self.graphql(REPO_QUERY, **variables)
            repository = data.get("repository")
            if repository is None:
                raise Gap("repository not found or not readable")
            connection = repository["projectsV2"]
            rows.extend(connection["nodes"])
            if not connection["pageInfo"]["hasNextPage"]:
                return rows
            after = connection["pageInfo"]["endCursor"]

    def project_fields(self, project_id):
        rows, after = [], None
        while True:
            variables = {"id": project_id}
            if after:
                variables["after"] = after
            data = self.graphql(FIELDS_QUERY, **variables)
            node = data.get("node")
            if node is None:
                raise Gap("project not found or not readable")
            connection = node["fields"]
            rows.extend(connection["nodes"])
            if not connection["pageInfo"]["hasNextPage"]:
                return rows
            after = connection["pageInfo"]["endCursor"]

    def issue(self, owner, name, number):
        data = self.graphql(ISSUE_QUERY, owner=owner, name=name, number=number)
        repository = data.get("repository")
        if repository is None:
            raise Gap("repository not found or not readable")
        issue = repository["issue"]
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
            for item in connection["nodes"]:
                content = item.get("content") or {}
                if content.get("id") is None:
                    continue
                value = item.get("fieldValueByName") or {}
                rows.append({"id": item["id"], "issue_id": content["id"],
                             "number": content.get("number"), "status": value.get("name")})
            if not connection["pageInfo"]["hasNextPage"]:
                return rows
            after = connection["pageInfo"]["endCursor"]

    def item_status(self, item_id):
        data = self.graphql(ITEM_QUERY, id=item_id)
        node = data.get("node")
        if node is None:
            raise Gap("project item not found")
        value = node.get("fieldValueByName") or {}
        return value.get("name")

    def add_item(self, project_id, content_id):
        data = self.graphql(ADD_ITEM_MUTATION, retry=False,
                            project=project_id, content=content_id)
        return data["addProjectV2ItemById"]["item"]["id"]

    def set_status(self, project_id, item_id, field_id, option_id):
        self.graphql(SET_STATUS_MUTATION, retry=False, project=project_id,
                     item=item_id, field=field_id, option=option_id)

    def assign(self, owner, name, number, login):
        output = self.gh(["api", "--method", "POST",
                          f"repos/{owner}/{name}/issues/{number}/assignees",
                          "-f", f"assignees[]={login}"])
        payload = json.loads(output)
        return [node.get("login") for node in payload.get("assignees", [])]

    def project_config(self, owner, name):
        try:
            output = self.gh(["api", f"repos/{owner}/{name}/contents/.github/issue-status.json",
                              "--jq", ".content"])
        except RuntimeError as error:
            message = str(error)
            if re.search(r"\b404\b", message):
                return {}
            raise Gap(f"could not read .github/issue-status.json: {message}")
        try:
            raw = base64.b64decode("".join(output.split())).decode("utf-8")
            config = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise Gap(f"invalid .github/issue-status.json: {error}")
        if not isinstance(config, dict):
            raise Gap(".github/issue-status.json must be a JSON object")
        return config

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
        rows, after = [], None
        while True:
            variables = {"owner": owner, "name": name, "number": number}
            if after:
                variables["after"] = after
            data = self.graphql(CLOSING_QUERY, **variables)
            repository = data.get("repository")
            if repository is None:
                raise Gap("repository not found or not readable")
            pull = repository["pullRequest"]
            if pull is None:
                raise Gap(f"PR #{number} not found")
            connection = pull["closingIssuesReferences"]
            rows.extend((node["repository"]["nameWithOwner"], node["number"])
                        for node in connection["nodes"])
            if not connection["pageInfo"]["hasNextPage"]:
                return rows
            after = connection["pageInfo"]["endCursor"]


def repository(value):
    owner, _, name = value.partition("/")
    if not owner or not name or "/" in name:
        raise argparse.ArgumentTypeError("use OWNER/REPO")
    return owner, name


def load_names(client, owner, name, config_path=None):
    """Resolve logical status names from a local file or the repository config."""
    config = (json.loads(Path(config_path).read_text(encoding="utf-8"))
              if config_path else client.project_config(owner, name))
    if not isinstance(config, dict):
        raise ValueError("config must be a JSON object")
    names, seen = {}, {}
    for role, default in TRANSITIONS.items():
        value = config.get(role, default)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{role} must be a nonempty status name")
        key = value.strip().casefold()
        if key in seen:
            raise ValueError(f"{role} and {seen[key]} use the same status name {value!r}")
        seen[key] = role
        names[role] = value.strip()
    project = config.get("project")
    if project is not None and (isinstance(project, bool) or not isinstance(project, int)):
        raise ValueError("project must be a number")
    return names, project


def report_config_gap(client, repo, args, error):
    """Report a config gap, still assigning at start when issue access allows."""
    owner, name = repo
    if args.pr is not None:
        print(f"issue status: {owner}/{name} PR #{args.pr}: untracked "
              f"(invalid issue-status config: {error})")
        return
    for number in args.issue:
        notes, assigned = [f"invalid issue-status config: {error}"], None
        if args.transition == "start":
            try:
                issue = client.issue(owner, name, number)
                assigned, more = assign_start(client, repo, number, issue,
                                              args.operator, args.dry_run)
                notes.extend(more)
            except Exception as failure:  # Bookkeeping must never fail the main work.
                notes.append(f"assignment failed: {failure}")
        suffix = f", assigned @{assigned}" if assigned else ""
        print(f"issue status: {owner}/{name}#{number}: untracked "
              f"({'; '.join(notes)}){suffix}")


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
    if args.transition == "pr":
        if args.pr is None:
            parser.error("pr requires --pr; closing references determine the issues")
        if args.issue:
            parser.error("pr uses --pr, not --issue")
    else:
        if args.pr is not None:
            parser.error("--pr applies only to the pr transition")
        if not args.issue:
            parser.error("give --issue (repeatable)")
    if args.transition == "done" and not (args.verified or "").strip():
        parser.error("done requires --verified with the deployment or release evidence")

    client = client or GitHub()
    owner, name = args.repo
    try:
        names, config_project = load_names(client, owner, name, args.config)
    except Exception as error:  # Bookkeeping must never fail the main work.
        report_config_gap(client, args.repo, args, error)
        return 0
    project_number = args.project if args.project is not None else config_project

    if args.pr is not None:
        try:
            references = client.closing_issues(owner, name, args.pr)
        except Exception as error:  # Bookkeeping must never fail the main work.
            print(f"issue status: {owner}/{name} PR #{args.pr}: untracked ({error})")
            return 0
        target = f"{owner}/{name}".casefold()
        numbers = [number for repo, number in references if repo.casefold() == target]
        for repo, number in references:
            if repo.casefold() != target:
                print(f"issue status: {repo}#{number}: untracked "
                      f"(external reference from {owner}/{name} PR #{args.pr})")
        if not numbers:
            print(f"issue status: {owner}/{name} PR #{args.pr}: untracked "
                  "(closes no issues in this repository)")
            return 0
    else:
        numbers = args.issue

    for number in numbers:
        try:
            result = apply(client, args.repo, number, args.transition,
                           operator=args.operator, verified=args.verified,
                           project_number=project_number, dry_run=args.dry_run,
                           names=names)
        except Exception as error:  # Bookkeeping must never fail the main work.
            result = {"repo": f"{owner}/{name}", "issue": number, "tracked": False,
                      "status": None, "assigned": None, "skipped": None,
                      "notes": [str(error)], "dry_run": args.dry_run, "failed": True}
        print(format_result(result, args.transition, args.verified))
    return 0


if __name__ == "__main__":
    sys.exit(main())
