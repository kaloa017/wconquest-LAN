# World Conquest

This is a game hosted locally on the internet. It's only accessible via the same Wi-Fi (or LAN) network. It's simply just a mix of [r/place](<https://en.wikipedia.org/wiki/R/place>) and territorial.io. 

In order for this to run, simply clone the project, install the Flask library, and run via

```bash
python app.py
```

Then it should now be accessible via the LAN.

## Changes to Make

### Factions
- [ ] Add faction research that provides bonuses to all faction members
- [ ] Add a shared faction army that all faction members can contribute to/use
- [ ] Allow factions to declare war on other factions
- [ ] Treat factions as the alliance system
- [ ] Remove the existing alliance proposal system
- [ ] Add faction settings:
  - [ ] Invite-only / join requests
  - [ ] Open faction
  - [ ] Closed faction
  - [ ] Other configurable settings
- [ ] When a player is kicked, prevent them from attempting to rejoin until the next day
- [ ] All members of the same faction should share the same color
- [ ] Faction members should be able to use faction-owned ports and airports
- [ ] Add meaningful uses for the faction treasury

### Research
- [ ] Add more research options
- [ ] Add faction-wide research
- [ ] Add military research
- [ ] Add nuclear research
- [ ] Add economic research
- [ ] Add transportation research
- [ ] Make research provide meaningful strategic bonuses

### Diplomacy
- [ ] Add embassies
- [ ] Allow embassies to unlock additional trading options
- [ ] Allow countries to specify what they want to receive in exchange for specific resources
- [ ] Add country capitals
- [ ] Display the capital as a star on the capital tile
- [ ] Allow embassies to be established at capitals
- [ ] Add ideologies
- [ ] Add more diplomatic interactions

### Economy
- [ ] Add a "Sell All" button to markets
- [ ] Allow players to sell individual tiles
- [ ] Selling a tile should return 50% of its purchase price
- [ ] Add more things to spend money on during the late game
- [ ] Add more resources
- [ ] Add buildings that generate specific resources
- [ ] Add resource costs when purchasing territories
- [ ] Rework territory pricing
- [ ] Base territory prices on approximate economic output and income
- [ ] Make territory prices more realistic based on how much they generate
- [ ] Add an economic statistics menu
- [ ] Show how much money/resources are generated over a selected period of time
- [ ] Give the treasury a meaningful purpose
- [ ] Make treasury donations useful
- [ ] Add treasury income of 1% of the treasury's current amount every 10 minutes

### Territory Management
- [ ] Add an option to delete/release all owned territories
- [ ] Require multiple confirmations before deleting all territories
- [ ] Improve land/water tile detection
- [ ] Make land and water tiles much more accurate
- [ ] Make it visually easier to distinguish land from water
- [ ] Show tile coordinates when hovering over tiles
- [ ] Add more useful information when hovering over tiles

### Boats & Transportation
- [ ] Boats should not require a nearby port to land
- [ ] Boats should have infinite range over sea tiles
- [ ] Boats should consume additional resources based on the number of sea tiles traveled
- [ ] Allow players to request to borrow another player's plane or ship
- [ ] Send the owner a notification when someone requests to borrow a vehicle
- [ ] Allow the requester to include a custom message
- [ ] Allow the owner to accept or deny the request
- [ ] Allow faction members to borrow vehicles from each other more freely
- [ ] Add a hotkey for attacking

### Nuclear Weapons
- [ ] Add nuclear bombs
- [ ] Make nuclear bombs extremely expensive
- [ ] Initial proposed cost: $100,000,000
- [ ] Require multiple research technologies before nuclear weapons can be created
- [ ] Require multiple specialized buildings for nuclear weapons
- [ ] Add a nuclear weapons progression system
- [ ] Nuclear attacks should remove territory ownership within a randomized radius
- [ ] Nuclear attack radius should be randomized between 3-10 tiles
- [ ] Apply a significant penalty to the country that gets hit
- [ ] Add nuclear power plants as a requirement for nuclear weapons
- [ ] Give nuclear power plants an extremely small chance of catastrophic failure
- [ ] If a nuclear power plant explodes, make nearby tiles permanently uninhabitable

### Administration & Chat
- [ ] Allow admins to edit messages sent by any player
- [ ] Allow admins to send messages as other accounts
- [ ] Add appropriate admin controls for managing messages
- [ ] Clearly distinguish administrator actions where necessary

### Country Merging
- [ ] Add a secret country merge feature
- [ ] Hide the merge feature from the normal UI
- [ ] Entering the Konami Code in chat should unlock the merge button
- [ ] Add the merge button to the faction menu
- [ ] Allow two accounts/countries to merge into one
- [ ] Require multiple confirmations before merging
- [ ] Correctly merge territories, money, resources, buildings, research, etc.

### Population
- [ ] Add total population to countries
- [ ] Display population in country statistics
- [ ] Make population interact with buildings, territories, resources, or other systems

### Achievements
- [ ] Add more achievements
- [ ] Add economic achievements
- [ ] Add territory achievements
- [ ] Add military achievements
- [ ] Add faction achievements
- [ ] Add research achievements
- [ ] Add diplomatic achievements
- [ ] Add nuclear achievements
- [ ] Add population achievements
- [ ] Add long-term progression achievements

### Customization
- [ ] Add custom country colors
- [ ] Make faction colors work consistently
- [ ] Countries in the same faction should use the faction's shared color

### Tutorial
- [ ] Add a tutorial for new players
- [ ] Explain how territory purchasing works
- [ ] Explain the economy
- [ ] Explain resources
- [ ] Explain buildings
- [ ] Explain research
- [ ] Explain factions
- [ ] Explain diplomacy
- [ ] Explain transportation
- [ ] Explain markets
- [ ] Explain military systems
- [ ] Explain other important game mechanics

### General Improvements
- [ ] Improve the overall UI clarity
- [ ] Make land and water tiles easier to identify
- [ ] Make economic information easier to understand
- [ ] Make faction mechanics easier to discover
- [ ] Add more strategic depth through research, resources, diplomacy, military, and economy
- [ ] Add confirmation dialogs for destructive actions
- [ ] Make sure all new systems integrate properly with existing mechanics
- [ ] Review existing mechanics for inconsistencies and improve them

## Want to contribute to this project?

Feel free to fork the project and do a merge request to contribute to this game. Thank you!
