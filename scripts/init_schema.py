#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["neo4j>=5.0.0"]
# ///
"""
Eva Memory - Neo4j Schema Initialization

Applies constraints + indexes to the default neo4j database.
Run once during setup: uv run scripts/init_schema.py

Env vars:
  EVA_NEO4J_URI  - bolt://neo4j:7687 (default)
  EVA_NEO4J_PASS - Neo4j password (required)
"""

import os
import sys
from pathlib import Path

from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("EVA_NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.environ.get("EVA_NEO4J_USER", "neo4j")
NEO4J_PASS = os.environ.get("EVA_NEO4J_PASS") or os.environ.get("NEO4J_PASSWORD")
DATABASE = "neo4j"


def main():
    if not NEO4J_PASS:
        print("ERROR: Set EVA_NEO4J_PASS or NEO4J_PASSWORD env var", file=sys.stderr)
        sys.exit(1)

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

    try:
        # Verify connectivity
        driver.verify_connectivity()
        print(f"Connected to Neo4j at {NEO4J_URI}")
        print(f"Using database: {DATABASE}")

        # Apply schema from init.cypher
        cypher_path = Path(__file__).parent.parent / "schema" / "init.cypher"
        if not cypher_path.exists():
            print(f"ERROR: Schema file not found: {cypher_path}", file=sys.stderr)
            sys.exit(1)

        cypher_text = cypher_path.read_text()

        # Split into individual statements (skip comments and empty lines)
        statements = []
        for line in cypher_text.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("//"):
                statements.append(stripped)

        # Join multi-line statements (they end with ;)
        full_statements = []
        current = ""
        for line in statements:
            current += " " + line if current else line
            if line.endswith(";"):
                full_statements.append(current.rstrip(";").strip())
                current = ""
        if current:
            full_statements.append(current.strip())

        with driver.session(database=DATABASE) as session:
            for stmt in full_statements:
                if stmt:
                    try:
                        session.run(stmt)
                        print(f"  OK: {stmt[:80]}...")
                    except Exception as e:
                        # Constraints/indexes may already exist
                        if "already exists" in str(e).lower() or "equivalent" in str(e).lower():
                            print(f"  SKIP (exists): {stmt[:60]}...")
                        else:
                            print(f"  FAIL: {stmt[:60]}... -> {e}", file=sys.stderr)

        print("\nSchema initialization complete.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
