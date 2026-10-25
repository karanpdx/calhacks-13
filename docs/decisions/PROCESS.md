# Decision log: process

This is how we record the important decisions behind each feature, so the team (and the judges) can see why we went
the way we did. The log itself is [LOG.md](LOG.md).

## When an entry is written

Every time a feature is finished, Claude writes one entry before the feature is called done. "Finished" means the
change is committed on the feature branch and its tests pass. A feature with no decision worth recording still gets an
entry that says so in one line.

## What goes in an entry

Each entry is at most **2 lines** under the heading:

```
## YYYY-MM-DD: <feature name>
<the choice we made>. Why: <the main reason, and what we gave up>.
```

Rules for the text:

- Name the choice concretely (for example "referee validates messages in code, not in an LLM"), not the feature.
- Give the reason in the same breath. If the reason is "the team agreed" or "it was faster", say that.
- No more than 2 lines. If it needs more, the choice is probably two decisions. Write two entries.
- Do not copy personal data, mandate values, keys, or CRS credentials into an entry.

## Where the source material comes from

The rule is to analyze the conversations of **all** people who worked on the feature, not just the current chat. Claude
can only see what is available in the repo and this session, so the sources are:

1. **Git history and PRs**: commit messages, PR descriptions and review comments for the feature's branch.
2. **Inbox drop**: `docs/decisions/inbox/`. Each teammate can export or paste the parts of their chat with Claude
   where a decision was made into a text file named `<name>-<feature>.md`. Claude reads every file in the inbox that
   matches the feature, then deletes the processed file so the inbox stays small. Teammates should keep only the
   decision-relevant parts and strip secrets and personal data before saving.
3. **This session**: the work and the reasoning in the current conversation.
4. **Existing docs**: `CLAUDE.md` hard rules and `docs/`, since they often record the reasons already.

If the sources disagree, the entry records the disagreement in its 2 lines rather than picking a side silently.

## Steps Claude follows

1. Collect sources for the feature (list above). Skip any source that is missing and say so in the final message.
2. Pull out the decisions that changed the design, scope or safety rules. Ignore routine code choices.
3. Write the entries at the top of the log file, newest first, using the format above.
4. Delete the processed inbox files for this feature.
5. Tell the user which entries were added, in one line each.

## Maintenance

- If a later feature reverses a decision, do not edit the old entry. Add a new entry that starts with
  "Reverses YYYY-MM-DD:" so the history stays honest.
- Keep the log short. Roughly one entry per feature is enough.
