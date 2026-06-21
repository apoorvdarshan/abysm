//
//  Creatures.swift
//  Abysm
//
//  The sea-life dataset: real species at their real depths (data from
//  neal.fun/deep-sea + cross-check), each with a one-line fact for the
//  neal.fun-style info card. Only species with a generated pixel sprite are
//  listed; the Abyss & Hadal zones (>4000 m) await more art credits.
//

import CoreGraphics

struct CreatureDef {
    let key: String         // asset = "creature_<key>"
    let name: String        // display name
    let depthM: CGFloat     // real depth in metres
    let width: CGFloat      // on-screen width in points (rough real-scale)
    let fact: String        // one-line fact (info card)
    var still: Bool = false // anchored (coral, tube worms) — no patrol
}

enum Creatures {

    static let all: [CreatureDef] = [
        // ── Sunlight Zone (0–200 m) ──
        CreatureDef(key: "salmon", name: "Atlantic Salmon", depthM: 3, width: 95,
                    fact: "Born in rivers, it swims thousands of miles out to sea and back to spawn."),
        CreatureDef(key: "manatee", name: "Manatee", depthM: 3, width: 200,
                    fact: "A gentle 'sea cow' that grazes seagrass and surfaces every few minutes to breathe."),
        CreatureDef(key: "coral", name: "Staghorn Coral", depthM: 12, width: 110,
                    fact: "A colony of tiny animals; coral reefs shelter about a quarter of all sea life.", still: true),
        CreatureDef(key: "polarbear", name: "Polar Bear", depthM: 23, width: 150,
                    fact: "The largest land carnivore — and a strong swimmer that hunts seals at the ice edge."),
        CreatureDef(key: "clownfish", name: "Clownfish", depthM: 37, width: 60,
                    fact: "Lives unharmed among a sea anemone's stinging tentacles, which guard it from predators."),
        CreatureDef(key: "bluetang", name: "Blue Tang", depthM: 45, width: 66,
                    fact: "A bright reef fish with a scalpel-sharp spine near its tail."),
        CreatureDef(key: "seadragon", name: "Leafy Sea Dragon", depthM: 53, width: 84,
                    fact: "A relative of the seahorse, camouflaged as drifting seaweed."),
        CreatureDef(key: "mahimahi", name: "Mahi-Mahi", depthM: 64, width: 115,
                    fact: "One of the fastest-growing fish, blazing with green-gold color."),
        CreatureDef(key: "beluga", name: "Beluga Whale", depthM: 79, width: 205,
                    fact: "The 'canary of the sea' — it chirps and whistles, and can even turn its head."),
        CreatureDef(key: "barracuda", name: "Great Barracuda", depthM: 95, width: 135,
                    fact: "A fierce ambush hunter with a mouthful of dagger-like teeth."),
        CreatureDef(key: "orca", name: "Orca", depthM: 99, width: 240,
                    fact: "The ocean's top predator; pods hunt as a team and speak their own dialects."),
        CreatureDef(key: "sealion", name: "Sea Lion", depthM: 135, width: 130,
                    fact: "Steers with its front flippers and can dive well past 130 m for fish."),
        CreatureDef(key: "bullshark", name: "Bull Shark", depthM: 150, width: 155,
                    fact: "Can survive in fresh water and has swum far up rivers."),
        CreatureDef(key: "turtle", name: "Green Sea Turtle", depthM: 170, width: 140,
                    fact: "Holds its breath for hours and navigates whole oceans back to its birth beach."),
        // ── Twilight Zone (200–1000 m) ──
        CreatureDef(key: "haddock", name: "Haddock", depthM: 220, width: 100,
                    fact: "A North Atlantic cod relative marked by a dark 'thumbprint' on its side."),
        CreatureDef(key: "wolfeel", name: "Wolf Eel", depthM: 223, width: 130,
                    fact: "Despite the name it's a fish, with strong jaws for crushing shellfish."),
        CreatureDef(key: "chaincatshark", name: "Chain Catshark", depthM: 233, width: 110,
                    fact: "A small shark whose chain-pattern skin glows green — it's biofluorescent."),
        CreatureDef(key: "greatwhite", name: "Great White Shark", depthM: 270, width: 180,
                    fact: "Senses a single drop of blood from far away using electroreception."),
        CreatureDef(key: "cockatoosquid", name: "Cockatoo Squid", depthM: 303, width: 95,
                    fact: "A glassy, transparent squid that can flush with reddish pigment."),
        CreatureDef(key: "blueshark", name: "Blue Shark", depthM: 353, width: 160,
                    fact: "A slim, ocean-roaming shark that migrates across entire oceans."),
        CreatureDef(key: "fireflysquid", name: "Firefly Squid", depthM: 377, width: 55,
                    fact: "Covers its body in tiny blue lights to lure prey and dazzle predators."),
        CreatureDef(key: "bigeyetuna", name: "Bigeye Tuna", depthM: 415, width: 120,
                    fact: "Spends the day in cold deep water and warms up near the surface."),
        CreatureDef(key: "seaangel", name: "Sea Angel", depthM: 460, width: 52,
                    fact: "A tiny shell-less sea snail that 'flies' on wing-like feet."),
        CreatureDef(key: "lanternfish", name: "Lanternfish", depthM: 500, width: 62,
                    fact: "Maybe the most abundant vertebrate on Earth, glowing with rows of light organs."),
        CreatureDef(key: "swordfish", name: "Swordfish", depthM: 550, width: 160,
                    fact: "Heats its eyes and brain so it can hunt fast in cold deep water."),
        CreatureDef(key: "nautilus", name: "Nautilus", depthM: 566, width: 90,
                    fact: "A 'living fossil' that jets through the water inside a spiral shell."),
        CreatureDef(key: "sunfish", name: "Ocean Sunfish", depthM: 580, width: 170,
                    fact: "The heaviest bony fish — it basks on its side to rewarm after deep dives."),
        CreatureDef(key: "spidercrab", name: "Japanese Spider Crab", depthM: 640, width: 150,
                    fact: "The largest crab on Earth — its legs can span over 3 metres."),
        CreatureDef(key: "coelacanth", name: "Coelacanth", depthM: 700, width: 130,
                    fact: "Believed extinct for 65 million years — until one was caught in 1938."),
        CreatureDef(key: "giantoctopus", name: "Giant Pacific Octopus", depthM: 758, width: 160,
                    fact: "The largest octopus; it can squeeze through any gap bigger than its beak."),
        CreatureDef(key: "oarfish", name: "Giant Oarfish", depthM: 800, width: 220,
                    fact: "The longest bony fish (to 8 m); old 'sea serpent' tales may be sightings of it."),
        // ── Midnight Zone (1000–4000 m) ──
        CreatureDef(key: "anglerfish", name: "Anglerfish", depthM: 1040, width: 100,
                    fact: "Dangles a glowing lure to draw prey into total darkness."),
        CreatureDef(key: "blobfish", name: "Blobfish", depthM: 1165, width: 90,
                    fact: "Looks gelatinous only at the surface — under deep pressure it's a normal fish."),
        CreatureDef(key: "frilledshark", name: "Frilled Shark", depthM: 1200, width: 150,
                    fact: "An eel-like 'living fossil' shark with 300 needle-like teeth."),
        CreatureDef(key: "goblinshark", name: "Goblin Shark", depthM: 1290, width: 150,
                    fact: "Shoots its jaws forward to snatch prey; another deep-sea 'living fossil.'"),
        CreatureDef(key: "hatchetfish", name: "Hatchetfish", depthM: 1370, width: 55,
                    fact: "Glows on its belly to erase its own silhouette from below."),
        CreatureDef(key: "dragonfish", name: "Dragonfish", depthM: 1450, width: 90,
                    fact: "Makes red light that it alone can see — a hidden hunting beam."),
        CreatureDef(key: "tubeworm", name: "Giant Tube Worm", depthM: 1550, width: 90,
                    fact: "Has no mouth or gut; it lives on bacteria fed by hot vent chemicals.", still: true),
        CreatureDef(key: "yeticrab", name: "Yeti Crab", depthM: 1650, width: 90,
                    fact: "Farms bacteria on its furry arms beside hydrothermal vents."),
        CreatureDef(key: "telescopeoctopus", name: "Telescope Octopus", depthM: 2000, width: 90,
                    fact: "Transparent, with tubular eyes that swivel to point upward."),
        CreatureDef(key: "giantisopod", name: "Giant Isopod", depthM: 2100, width: 90,
                    fact: "A deep-sea cousin of the woodlouse that can go years between meals."),
        CreatureDef(key: "greenlandshark", name: "Greenland Shark", depthM: 2160, width: 180,
                    fact: "May live over 400 years — the longest-lived vertebrate known."),
        CreatureDef(key: "colossalsquid", name: "Colossal Squid", depthM: 2200, width: 200,
                    fact: "Has the largest eyes of any animal — about the size of dinner plates."),
        CreatureDef(key: "barreleye", name: "Barreleye", depthM: 2300, width: 80,
                    fact: "Sees upward through its own transparent, fluid-filled forehead."),
        CreatureDef(key: "viperfish", name: "Viperfish", depthM: 2800, width: 90,
                    fact: "Fangs so long they don't fit inside its mouth."),
        CreatureDef(key: "vampiresquid", name: "Vampire Squid", depthM: 2903, width: 90,
                    fact: "No vampire — it eats 'marine snow' and turns inside-out to hide."),
        CreatureDef(key: "gulpereel", name: "Gulper Eel", depthM: 3060, width: 120,
                    fact: "A huge balloon-like mouth lets it swallow prey larger than itself."),
        CreatureDef(key: "cookiecutter", name: "Cookiecutter Shark", depthM: 3400, width: 80,
                    fact: "Bites round plugs of flesh from whales, sharks, even submarines."),
        CreatureDef(key: "dumbooctopus", name: "Dumbo Octopus", depthM: 3952, width: 95,
                    fact: "Flaps ear-like fins to 'fly' through the deep — the deepest-living octopus.")
    ]
}
