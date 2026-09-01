# Security Policy

This repository is the source for Artie's **hosted** MCP integration at `https://mcp.artie.com/mcp`. Artie Dashboard and API remain the authorization authority for identity, grants, environment binding, scopes, audit, and resource access.

## Reporting a vulnerability

**Do not open a public GitHub issue, discussion, or pull request for a security vulnerability.**

Report privately via [GitHub private vulnerability reporting](https://github.com/artie-labs/artie-mcp/security/advisories/new). Include enough detail to reproduce. Do not attach customer data, production credentials, or live pipeline identifiers.

## Coordinated disclosure

Artie Engineering owns intake and response for this repository.

- We will acknowledge a valid report as soon as we can, typically within 5 business days.
- We will work with you on a fix and a disclosure timeline before any public write-up.
- Please do not publish exploit details until we confirm a fix is available or we agree a date.

## Scope

In scope: this MCP server process, its policy-contract compiler, request/response shaping, authentication exchange to Artie API, published container image, and CI that builds them.

Out of scope for this repository's disclosure process (use Artie account/support channels instead): Dashboard/API authorization bugs that are not reachable through MCP, customer pipeline incidents, and account access problems.

## Supported versions

Only the code and images that Artie currently runs for the hosted service are supported. There is no supported self-hosted production deployment of this server.
