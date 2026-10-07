#!/bin/sh
# fake public check: passes iff the answer JSON contains the word fix
grep -q fix "${EQ_ANSWER:-.eq_answer.json}"
