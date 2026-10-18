# The product knowledge corpus

Everything in this directory is content the assistant is allowed to state as fact
about Evecta. Nothing else is. If a question is not answered by a document here, the
assistant says so rather than guessing — that is the point of the feature, and a
weak document is worse than a missing one.

`README.md` is this contract and is not itself indexed.

## Adding or changing a document

1. Write it as `some-topic.md` with the frontmatter below.
2. Screen it against **What must never go in** below.
3. Rebuild the index — **this is not optional**:

   ```
   env/Scripts/python.exe scripts/build_knowledge_index.py
   ```

4. Commit the document *and* the regenerated `../index_data.json` together.

If you skip step 3 the index no longer matches the corpus, the drift guard marks it
unavailable, and **the assistant stops answering product questions entirely** until
it is rebuilt. It fails that way on purpose: answering out of a document you have
just edited or deleted is the worse outcome.

## Required frontmatter

```yaml
---
title: How lead credits work        # what the assistant names as its source
audience: customer                  # who the document is written for
version: 3                          # bump on any substantive change
last_reviewed: 2026-08-01           # ISO date; a person confirmed this is accurate
---
```

All four are mandatory. A document missing any of them fails the build rather than
being indexed with a default.

`last_reviewed` is load-bearing: a document not reviewed within 12 months is treated
as stale and silently drops out of retrieval. Re-read it and move the date.

## What must never go in

- Secrets, API keys, credentials, connection strings.
- Environment configuration, infrastructure detail, server or application logs.
- Internal engineering notes, architecture docs, or anything in the repository's
  `docs/` directory — that material is written for engineers and is out of scope by
  definition.
- Unreleased plans, pricing under discussion, or roadmap commitments.
- Any customer data: names, companies, leads, campaigns, email content, usage.

The last one is absolute. This corpus is global — every user who asks the same
question gets the same documents, with no filtering by who is asking — so anything
customer-specific in here is disclosed to everyone.

## Writing for retrieval

- One topic per document; split rather than appending an unrelated section.
- Use `##` headings generously. Documents are chunked on headings, so a heading is
  the boundary the retriever scores against, and a wall of prose under one heading
  retrieves badly.
- Lead each section with the question a user would actually ask, in their words.
- State the behaviour plainly. The assistant may only say what these documents say,
  so an answer that is vague here is a vague answer in the product.
