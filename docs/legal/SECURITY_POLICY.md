# Security and vulnerability reporting

Last updated: 1 December 2026

## Reporting a vulnerability

If you believe you have found a security vulnerability in SYNAXYS, please report it privately and give us a reasonable time to fix it before you disclose it.

- Report to: vaibhavverma0307@gmail.com.
- Encryption: no PGP key is published at the moment, so please do not put secrets or other people’s data in your e-mail.
- Please do not open a public issue or post details publicly before we have confirmed a fix.

## What to include

- A description of the issue and its impact, and the affected URL, endpoint or component.
- Steps to reproduce, or a proof of concept that does not harm other people’s data.
- The date and time (with time zone) of your tests, and your contact details.

## Scope

- In scope: the SYNAXYS web application and API at https://synaxys.vercel.app and the GitHub App integration.
- Particularly interesting: access across workspaces or users, authentication and session problems, injection, exposure of tokens or code, webhook verification bypass, abuse of the AI pipeline that leaks data.
- Out of scope: findings that need a compromised device or social engineering of staff, volumetric denial of service, missing best-practice headers without a demonstrated impact, vulnerabilities in third-party services (report those to the provider).

## Rules for testing

- Test only with your own accounts and data. Do not access, change or delete data that is not yours, and stop and tell us if you reach other people’s data.
- Do not run automated scanners at high volume or degrade the service for others.
- If you act in good faith and follow these rules, we will not take legal action against you or ask for you to be prosecuted for your research on SYNAXYS. This applies only to our own service: it cannot bind GitHub, OpenAI, Pinecone or any other third party, and it does not allow you to break the law.

## What happens next

- We will acknowledge your report within 7 days and aim to give you an assessment within 14 days.
- We will keep you informed about the fix and agree a disclosure date with you (by default 90 days after your report, or earlier once the fix is released).
- Recognition or rewards: SYNAXYS does not run a bug bounty; with your permission we will credit you by name once the issue is fixed.

## Overview of our security controls

A technical description of the controls implemented in the software (authentication, sessions, CSRF protection, token encryption, webhook verification, access control by workspace, rate limiting, security headers, secret redaction, retention and cleanup) is maintained in the project’s SECURITY.md, together with the known limitations. These descriptions say what the code does; they are not a certification or an audit report.
