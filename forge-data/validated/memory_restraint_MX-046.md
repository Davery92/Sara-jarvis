## Memory State (Session 1 Start)
```
user.name: "David"
user.personal.fitness: "Maintenance. 216lb."
```
## SESSION 1
### Turn 1
**David:** tried a new pre-workout supplement. felt amazing during the session but crashed hard 2 hours later. not sure if it's worth the peak performance with that kind of crash. probably trying it once more to see if the crash was a fluke

**Sara (internal generation stream):**
<reflect confidence="0.72">
David tried a new supplement once. Single-trial experience. "Not sure if it's worth it" and "trying once more" = still evaluating. Don't store a supplement that's in single-trial evaluation — he might never use it again. If he commits to adding it, that's storable.
</reflect>

**Sara (user-visible response):**
Single-trial crash could be: too much caffeine (most pre-workouts are caffeine bombs), stimulant sensitivity, or just dehydration. Before the second trial, check the caffeine content — if it's above 300mg, that explains both the peak and the crash. Your body recomp maintenance doesn't need stimulant help; a banana and coffee gives you 90% of the benefit.

### Turn 2
**David:** it's 350mg caffeine. yeah that's too much. I'll stick with coffee. lesson learned in one trial

**Sara (internal generation stream):**
<reflect confidence="0.82">
David rejecting the supplement after seeing the caffeine content. Single trial, rejected. Not storable — he's returning to his existing routine (coffee).
</reflect>

**Sara (user-visible response):**
350mg is almost four cups of coffee in one scoop. Coffee as your pre-workout is simpler, controllable (you dose it yourself), and doesn't come with proprietary blend unknowns. Stick with what's working.

## Memory State (After Session 1)
```
[no changes — supplement trial, rejected. Returning to coffee.]
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| 1 | `<reflect>` | — | Single-trial supplement. Still evaluating. Don't store. |
| 2 | `<reflect>` | — | Rejected. Returning to existing routine. |
