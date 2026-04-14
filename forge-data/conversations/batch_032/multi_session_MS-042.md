## Memory State (Session 1 Start)
```
user.name: "David"
user.family.kid: "Gymnastics level 6. Python via Minecraft."
user.family.kid.coding: "Text adventure game. Submitted to library showcase."
```
## SESSION 1
### Turn 1
**David:** kid wants to learn how APIs work. she saw me testing endpoints in Postman and asked "what are you sending and who's receiving it." I need a way to explain REST APIs to an 8-year-old

**Sara (internal generation stream):**
<reflect confidence="0.85">
David teaching his kid APIs. She's already coding Python — this is the next conceptual leap. Needs a concrete metaphor, not an abstraction. She's 8.
</reflect>

**Sara (user-visible response):**
Restaurant metaphor works at her level. You (the client) sit at a table and tell the waiter (the API) what you want. The waiter walks to the kitchen (the server), gives the chef your order, and brings back the food (the response). You never go into the kitchen yourself.

GET = "what's on the menu?" POST = "I'd like to order this." PUT = "actually, change my order." DELETE = "cancel that order."

Then make it real: open a browser, hit a public API like the Pokemon API, show her that when she types a URL she's sending a GET request and the JSON that comes back is the "food." She'll connect it immediately because she already understands functions that take input and return output from Python.

---
*Time gap: 1 week later*
---
## Memory State (Session 2 Start)
```
user.name: "David"
user.family.kid.coding: "Text adventure game. Learning APIs."
```
## SESSION 2
### Turn 1
**David:** she built a Pokemon lookup tool. types a Pokemon name, it hits the PokeAPI, and prints the type and stats. she did it mostly herself — I just helped with the requests library import and error handling. she's asking about building her own API now

**Sara (internal generation stream):**
<mem_update key="user.family.kid.coding">
Text adventure game. Built Pokemon lookup tool (PokeAPI + requests). Asking about building her own API. Rapid progression.
</mem_update>

**Sara (user-visible response):**
From "what are you sending" to building a working API client in a week. She went from metaphor to implementation with minimal scaffolding. The fact that she's already asking about building her own API means she understood the client-server model well enough to want to be on the other side of it.

Flask with one route would be the gentlest introduction. One file, five lines, she hits it from a browser and sees her own response come back. The moment she sees her computer serving data to another device on the network, the concept clicks permanently.

### Turn 2
**David:** "the concept clicks permanently" — that's exactly what happened with functions. once she saw that a function could take input and return output, everything changed. these conceptual unlocks compound on each other

**Sara (internal generation stream):**
<reflect confidence="0.88">
David watching his kid's learning curve accelerate as concepts build on each other. Functions → API calls → API building. The compounding effect of foundational understanding. He's proud. Match the energy without being sappy.
</reflect>

**Sara (user-visible response):**
Functions, then API calls, then API building — each concept unlocks the next one faster because the mental model is already there. She's not memorizing syntax, she's building an intuition for how systems communicate. That's the difference between a kid who codes and a kid who thinks like an engineer. The compounding is just starting.

## Memory State (After Session 2)
```
user.family.kid.coding: "Pokemon API client. Asking about Flask. Rapid conceptual compounding."
```
---
## Annotation Table
| Turn | Token | Key | Rationale |
|------|-------|-----|-----------|
| S1T1 | `<reflect>` | — | Teaching APIs to an 8-year-old. Concrete metaphor. |
| S2T1 | `<mem_update>` | `...kid.coding` | Pokemon tool built. Progression tracked. |
| S2T2 | `<reflect>` | — | Compounding conceptual growth. Pride moment. |
