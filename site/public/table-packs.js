// Game night's packs (duecrew.com/table): written for Due Crew, plain medical
// facts, no deck, bank or video series named, and nothing from anyone's
// deck. Imposter's twins (topics easy to mix up, with what tells them
// apart and the bots' clue words), Rounds' black and white cards, Trivia's
// questions, Draw it's prompts and the bots' doodles (strokes as text, two
// characters a point, in table.js's alphabet), Somewhere between's ends
// (with where some things sit, for the bots), and Links' clue words.
"use strict";
const GN_PACKS = {
 "imp": [
  {
   "part": "Renal › Glomerular",
   "a": {
    "t": "Nephrotic syndrome",
    "facts": [
     "Protein over 3.5 g a day",
     "Edema, low albumin",
     "High lipids, foamy urine"
    ],
    "clues": [
     "foamy",
     "edema",
     "albumin",
     "lipids",
     "proteinuria",
     "podocytes"
    ]
   },
   "b": {
    "t": "Nephritic syndrome",
    "facts": [
     "Blood and RBC casts",
     "Hypertension",
     "Less urine, often after strep"
    ],
    "clues": [
     "casts",
     "hematuria",
     "strep",
     "hypertension",
     "oliguria",
     "cola"
    ]
   }
  },
  {
   "part": "Endocrine › Thyroid",
   "a": {
    "t": "Graves disease",
    "facts": [
     "Antibodies switch the TSH receptor on",
     "Bulging eyes, swollen shins",
     "Hyperthyroid: heat, weight loss, tremor"
    ],
    "clues": [
     "bulging",
     "shins",
     "tremor",
     "heat",
     "stimulating",
     "sweaty"
    ]
   },
   "b": {
    "t": "Hashimoto thyroiditis",
    "facts": [
     "Antibodies against TPO destroy the gland",
     "Hypothyroid: cold, tired, weight gain",
     "Lymphocytes fill the thyroid"
    ],
    "clues": [
     "TPO",
     "cold",
     "tired",
     "lymphocytes",
     "goiter",
     "sluggish"
    ]
   }
  },
  {
   "part": "GI › Bowel",
   "a": {
    "t": "Crohn disease",
    "facts": [
     "Anywhere mouth to anus, skip lesions",
     "Transmural: fistulas, strictures",
     "Granulomas, cobblestones"
    ],
    "clues": [
     "skip",
     "fistula",
     "transmural",
     "granulomas",
     "cobblestone",
     "ileum"
    ]
   },
   "b": {
    "t": "Ulcerative colitis",
    "facts": [
     "Starts at the rectum, continuous",
     "Mucosa only",
     "Bloody diarrhea, linked to PSC"
    ],
    "clues": [
     "rectum",
     "continuous",
     "mucosal",
     "bloody",
     "PSC",
     "pseudopolyps"
    ]
   }
  },
  {
   "part": "Endocrine › Pancreas",
   "a": {
    "t": "Type 1 diabetes",
    "facts": [
     "Autoimmune loss of beta cells",
     "Young, thin, DKA",
     "Needs insulin from the start"
    ],
    "clues": [
     "autoimmune",
     "DKA",
     "young",
     "islets",
     "thin",
     "insulin"
    ]
   },
   "b": {
    "t": "Type 2 diabetes",
    "facts": [
     "Insulin resistance",
     "Obesity, family history",
     "Metformin first"
    ],
    "clues": [
     "resistance",
     "obesity",
     "metformin",
     "HHS",
     "adult",
     "acanthosis"
    ]
   }
  },
  {
   "part": "Endocrine › Adrenal",
   "a": {
    "t": "Cushing syndrome",
    "facts": [
     "Too much cortisol",
     "Moon face, striae, buffalo hump",
     "Dexamethasone suppression test"
    ],
    "clues": [
     "moon",
     "striae",
     "hump",
     "excess",
     "dexamethasone",
     "bruising"
    ]
   },
   "b": {
    "t": "Addison disease",
    "facts": [
     "Too little cortisol and aldosterone",
     "Dark skin, low pressure, salt craving",
     "High potassium"
    ],
    "clues": [
     "bronze",
     "salt",
     "hypotension",
     "craving",
     "potassium",
     "insufficiency"
    ]
   }
  },
  {
   "part": "MSK › Joints",
   "a": {
    "t": "Osteoarthritis",
    "facts": [
     "Wear and tear",
     "Worse with use, short morning stiffness",
     "Heberden and Bouchard nodes"
    ],
    "clues": [
     "wear",
     "Heberden",
     "weight",
     "osteophytes",
     "DIP",
     "crepitus"
    ]
   },
   "b": {
    "t": "Rheumatoid arthritis",
    "facts": [
     "Autoimmune synovitis",
     "Morning stiffness over an hour",
     "MCPs and PIPs, ulnar drift"
    ],
    "clues": [
     "morning",
     "MCP",
     "pannus",
     "ulnar",
     "symmetric",
     "CCP"
    ]
   }
  },
  {
   "part": "Pharm › Diuretics",
   "a": {
    "t": "Loop diuretics",
    "facts": [
     "Block NKCC2 in the thick ascending limb",
     "You lose calcium",
     "Ototoxic"
    ],
    "clues": [
     "furosemide",
     "Henle",
     "NKCC2",
     "ototoxic",
     "calcium",
     "potent"
    ]
   },
   "b": {
    "t": "Thiazides",
    "facts": [
     "Block NCC in the distal tubule",
     "You keep calcium",
     "Raise glucose, lipids and uric acid"
    ],
    "clues": [
     "distal",
     "hydrochlorothiazide",
     "hypercalcemia",
     "NCC",
     "sulfa",
     "gout"
    ]
   }
  },
  {
   "part": "Pulm › Obstructive",
   "a": {
    "t": "Asthma",
    "facts": [
     "Obstruction that reverses",
     "Young, eczema, allergies",
     "Wheeze that a bronchodilator fixes"
    ],
    "clues": [
     "reversible",
     "eczema",
     "triggers",
     "eosinophils",
     "Curschmann",
     "inhaler"
    ]
   },
   "b": {
    "t": "COPD",
    "facts": [
     "Obstruction that doesn't reverse",
     "Smokers",
     "Barrel chest, pursed lips"
    ],
    "clues": [
     "smoking",
     "barrel",
     "emphysema",
     "pursed",
     "irreversible",
     "bronchitis"
    ]
   }
  },
  {
   "part": "Endocrine › Water",
   "a": {
    "t": "SIADH",
    "facts": [
     "Too much ADH",
     "Low sodium, concentrated urine",
     "Small cell lung cancer"
    ],
    "clues": [
     "hyponatremia",
     "concentrated",
     "lung",
     "euvolemic",
     "restriction",
     "tolvaptan"
    ]
   },
   "b": {
    "t": "Diabetes insipidus",
    "facts": [
     "Too little ADH, or kidneys that ignore it",
     "Lots of dilute urine",
     "High sodium if you can't drink"
    ],
    "clues": [
     "dilute",
     "thirst",
     "polyuria",
     "desmopressin",
     "lithium",
     "hypernatremia"
    ]
   }
  },
  {
   "part": "Heme › Anemia",
   "a": {
    "t": "Iron deficiency anemia",
    "facts": [
     "Small red cells",
     "Low ferritin",
     "Blood loss, pica"
    ],
    "clues": [
     "microcytic",
     "ferritin",
     "pica",
     "spoon",
     "bleeding",
     "menorrhagia"
    ]
   },
   "b": {
    "t": "B12 deficiency",
    "facts": [
     "Big red cells",
     "Neuro signs, high MMA",
     "Pernicious anemia, vegans"
    ],
    "clues": [
     "macrocytic",
     "neuropathy",
     "pernicious",
     "MMA",
     "vegan",
     "hypersegmented"
    ]
   }
  },
  {
   "part": "Neuro › Junction",
   "a": {
    "t": "Myasthenia gravis",
    "facts": [
     "Antibodies to ACh receptors",
     "Weaker with use",
     "Ptosis, thymoma"
    ],
    "clues": [
     "ptosis",
     "fatigable",
     "thymoma",
     "receptor",
     "pyridostigmine",
     "diplopia"
    ]
   },
   "b": {
    "t": "Lambert-Eaton syndrome",
    "facts": [
     "Antibodies to calcium channels",
     "Stronger with use",
     "Small cell lung cancer"
    ],
    "clues": [
     "calcium",
     "improves",
     "lung",
     "presynaptic",
     "reflexes",
     "dry"
    ]
   }
  },
  {
   "part": "Cardio › Valves",
   "a": {
    "t": "Aortic stenosis",
    "facts": [
     "Crescendo-decrescendo at the right sternal border",
     "Syncope, angina, heart failure",
     "A calcified valve in the elderly"
    ],
    "clues": [
     "crescendo",
     "syncope",
     "calcified",
     "elderly",
     "angina",
     "carotids"
    ]
   },
   "b": {
    "t": "Mitral stenosis",
    "facts": [
     "Opening snap, diastolic rumble",
     "Rheumatic fever",
     "Atrial fibrillation, a big left atrium"
    ],
    "clues": [
     "rumble",
     "snap",
     "rheumatic",
     "diastolic",
     "atrium",
     "hoarseness"
    ]
   }
  }
 ],
 "blacks": [
  {
   "t": "____ toxicity: nausea, a yellow-green halo around every light, and a very worried cardiologist.",
   "a": "Digoxin",
   "why": "Nausea, vision changes, arrhythmias. Low potassium makes it worse."
  },
  {
   "t": "Orange tears, orange sweat, orange everything. Thanks, ____.",
   "a": "Rifampin",
   "why": "It turns body fluids red-orange. Harmless, and worth a warning."
  },
  {
   "t": "A fast infusion, a flushed red upper body and one very itchy patient: ____.",
   "a": "Vancomycin",
   "why": "Red man syndrome is histamine release. Slow the infusion."
  },
  {
   "t": "The dry cough started two weeks after ____.",
   "a": "ACE inhibitors",
   "why": "Bradykinin builds up. An ARB doesn't do it."
  },
  {
   "t": "Blue-gray skin, stiff lungs and a thyroid that's off: ____.",
   "a": "Amiodarone",
   "why": "Pulmonary fibrosis, thyroid swings both ways, skin discoloration."
  },
  {
   "t": "Tremor, thirst, and kidneys that stopped listening to ADH: ____.",
   "a": "Lithium",
   "why": "Nephrogenic diabetes insipidus, and a narrow therapeutic window."
  },
  {
   "t": "____ and grapefruit juice: a classic bad date.",
   "a": "Statins",
   "why": "Grapefruit blocks CYP3A4 and raises some statin levels: muscle damage."
  },
  {
   "t": "Gynecomastia in a man on heart failure meds? Blame ____.",
   "a": "Spironolactone",
   "why": "It blocks androgen receptors too. Eplerenone doesn't."
  },
  {
   "t": "Hold it before the CT contrast: ____.",
   "a": "Metformin",
   "why": "Lactic acidosis is the rare, serious one, worse with kidney failure."
  },
  {
   "t": "Hearing loss and kidney damage, together: ____.",
   "a": "Aminoglycosides",
   "why": "Ototoxic and nephrotoxic, and worse alongside loop diuretics."
  },
  {
   "t": "One drink and it's flushing, vomiting and regret: ____.",
   "a": "Metronidazole",
   "why": "A disulfiram-like reaction. No alcohol during, or for days after."
  },
  {
   "t": "A gout flare a month after starting ____.",
   "a": "Thiazides",
   "why": "They cut uric acid excretion."
  },
  {
   "t": "Isoniazid's numb feet get better with ____.",
   "a": "Vitamin B6",
   "why": "Isoniazid depletes pyridoxine. Give it alongside."
  },
  {
   "t": "Gray-stained teeth? Somebody took ____ in pregnancy.",
   "a": "Tetracyclines",
   "why": "They bind calcium in teeth and bone: not in pregnancy or young kids."
  },
  {
   "t": "A 70-year-old's Achilles tendon snapped on ____.",
   "a": "Fluoroquinolones",
   "why": "Tendon rupture risk rises with age and steroids."
  },
  {
   "t": "Wheezing and a heart rate of 40 after a dose of ____.",
   "a": "Beta blockers",
   "why": "Nonselective ones can trigger bronchospasm and slow the heart."
  },
  {
   "t": "Peaked T waves: protect the heart first with ____.",
   "a": "Calcium gluconate",
   "why": "It doesn't lower potassium. It steadies the heart while you do."
  },
  {
   "t": "Monthly blood counts and a black box warning: ____.",
   "a": "Clozapine",
   "why": "Agranulocytosis risk. Check the ANC."
  }
 ],
 "whites": [
  "ACE inhibitors",
  "Aminoglycosides",
  "Amiodarone",
  "Aspirin",
  "Beta blockers",
  "Caffeine",
  "Calcium gluconate",
  "Clozapine",
  "Digoxin",
  "Ethambutol",
  "Fluoroquinolones",
  "Furosemide",
  "Heparin",
  "Insulin",
  "Isoniazid",
  "Levothyroxine",
  "Lithium",
  "Metformin",
  "Metronidazole",
  "Morphine",
  "Naloxone",
  "Omeprazole",
  "Penicillin",
  "Prednisone",
  "Rifampin",
  "Spironolactone",
  "Statins",
  "Tetracyclines",
  "Thiazides",
  "Vancomycin",
  "Vitamin B6",
  "Warfarin"
 ],
 "wild": [
  "A very confident MS3",
  "The night-float intern",
  "Your attending's favorite mnemonic",
  "Grapefruit juice",
  "A 3-hour lecture on the Krebs cycle",
  "The vending machine on the fourth floor",
  "Pharmacology at 8 a.m.",
  "Whatever the resident said",
  "Two coffees and a prayer",
  "The one slide that's on every exam",
  "A highlighter that's run dry",
  "Eight hours of sleep",
  "The patient who read about it online",
  "Your review count this morning",
  "A pager going off mid-sentence",
  "The scrub machine"
 ],
 "trivia": [
  {
   "q": "Two weeks into a new drug, a dry cough that won't quit. The drug?",
   "opts": [
    "ACE inhibitor",
    "ARB",
    "Beta blocker",
    "Thiazide"
   ],
   "ans": 0
  },
  {
   "q": "Flushing and itching across the upper body during a fast infusion of ____.",
   "opts": [
    "Gentamicin",
    "Vancomycin",
    "Penicillin",
    "Linezolid"
   ],
   "ans": 1
  },
  {
   "q": "RBC casts on the urinalysis point to ____.",
   "opts": [
    "Nephrotic syndrome",
    "Acute tubular necrosis",
    "Nephritic syndrome",
    "Pyelonephritis"
   ],
   "ans": 2
  },
  {
   "q": "The most common cause of high calcium in an outpatient?",
   "opts": [
    "Primary hyperparathyroidism",
    "Cancer",
    "Thiazides",
    "Sarcoidosis"
   ],
   "ans": 0
  },
  {
   "q": "Wernicke encephalopathy: which vitamin?",
   "opts": [
    "Thiamine (B1)",
    "B12",
    "Pyridoxine (B6)",
    "Niacin (B3)"
   ],
   "ans": 0
  },
  {
   "q": "A string-of-beads renal artery in a young woman?",
   "opts": [
    "Fibromuscular dysplasia",
    "Atherosclerosis",
    "Takayasu arteritis",
    "Coarctation"
   ],
   "ans": 0
  },
  {
   "q": "First choice for absence seizures?",
   "opts": [
    "Ethosuximide",
    "Phenytoin",
    "Carbamazepine",
    "Phenobarbital"
   ],
   "ans": 0
  },
  {
   "q": "Kayser-Fleischer rings point to ____.",
   "opts": [
    "Wilson disease",
    "Hemochromatosis",
    "Alpha-1 antitrypsin deficiency",
    "Primary biliary cholangitis"
   ],
   "ans": 0
  },
  {
   "q": "The antidote for an acetaminophen overdose?",
   "opts": [
    "N-acetylcysteine",
    "Naloxone",
    "Flumazenil",
    "Fomepizole"
   ],
   "ans": 0
  },
  {
   "q": "A midshaft humerus fracture puts which nerve at risk?",
   "opts": [
    "Radial",
    "Axillary",
    "Ulnar",
    "Median"
   ],
   "ans": 0
  },
  {
   "q": "A cherry-red macula and no big liver or spleen?",
   "opts": [
    "Tay-Sachs",
    "Niemann-Pick",
    "Gaucher",
    "Fabry"
   ],
   "ans": 0
  },
  {
   "q": "Where does colorectal cancer spread first, most often?",
   "opts": [
    "Liver",
    "Lung",
    "Bone",
    "Brain"
   ],
   "ans": 0
  },
  {
   "q": "The incretin that boosts insulin after a meal?",
   "opts": [
    "GLP-1",
    "Glucagon",
    "Somatostatin",
    "Cortisol"
   ],
   "ans": 0
  },
  {
   "q": "A positive Babinski in an adult means a lesion of the ____.",
   "opts": [
    "Upper motor neuron",
    "Lower motor neuron",
    "Cerebellum",
    "Neuromuscular junction"
   ],
   "ans": 0
  },
  {
   "q": "Peaked T waves on the ECG?",
   "opts": [
    "Hyperkalemia",
    "Hypokalemia",
    "Hypercalcemia",
    "Hyponatremia"
   ],
   "ans": 0
  }
 ],
 "draw": [
  "Heart attack",
  "Kidney stone",
  "Red blood cell",
  "Neuron",
  "Migraine",
  "Overdose",
  "Appendicitis",
  "Broken arm",
  "Asthma attack",
  "Hernia",
  "Sneeze",
  "Tooth decay",
  "Stroke",
  "Gallstones",
  "Pneumonia",
  "Allergy",
  "Fever",
  "Insomnia",
  "Pregnancy",
  "Hiccups"
 ],
 "doodles": {
  "Heart attack": {
   "k": [
    "P@P@Q=R:U7X4^1c1i2n4r8u=vCuIrNnTiYc^^cXgUkRoQrPsPtPsOrNoKkHgCc>^8Y3T/N,I+C,=/83482>1C1H4K7N:O=P@P@",
    "R6JDVNL]Ti"
   ],
   "guess": "Broken heart?"
  },
  "Kidney stone": {
   "k": [
    "]P^S`Wb]cbbg`k]oYqUtRuNvJvFvBu?t;q8o5l2h0d._-Z,U,P,K-F.B0=295582;0?-B,F+J+N+R,U-Y0]2`6b:c?bD`I^M]P",
    "_Tkaow",
    "`P_R^S[TYSXRWPXNYM[L^M_N`P"
   ],
   "guess": "A bean with a pebble in it"
  },
  "Red blood cell": {
   "k": [
    "sPrVq]nbkggkbn]qVrPsJrDq?n:k6g3b0]/V.P/J0D3?6::6?3D0J/P.V/]0b3g6k:n?qDrJsP",
    "_P^T[XX[T^P_L^H[EXCTBPCLEHHELCPBTCXE[H^L_P"
   ],
   "guess": "A donut"
  },
  "Neuron": {
   "k": [
    "KPJSIVFYCZ@[=Z:Y7V6S5P6M7J:G=F@ECFFGIJJMKP",
    "KPsP",
    "sP{H",
    "sP{X",
    "sP|P",
    "8H*<",
    "8X*e",
    ">E<2",
    ">[:q"
   ],
   "guess": "A tree. A sad tree."
  },
  "Migraine": {
   "k": [
    "eTeYc_ac]gXkTmOoJoEo@m<k8g4c2_0Y0T0O2J4F8B<>@<E:J:O:T<X>]BaFcJeOeT",
    "e4]@gB_P",
    "s@kJuLmZ"
   ],
   "guess": "Lightning head"
  },
  "Overdose": {
   "k": [
    ":J8J6I4H2F1D0B0@0>1<2:486786:6N6N6P6R7T8V:W<X>X@XBWDVFTHRIPJNJ:J",
    "D6DJ",
    "JoHoFnDmBkAi@g@e@cAaB_D]F[HZJZaZaZcZe[g]i_jakckekgjiikgmencoaoJo",
    "UZUo",
    "vDuGtJqLoMkMiLfJeGdDeAf>i<k;o;q<t>uAvD"
   ],
   "guess": "Vitamins?"
  }
 },
 "botGuess": [
  "A kidney?",
  "Abstract art",
  "Is that a liver?",
  "Appendicitis!",
  "A very sad cell",
  "The Krebs cycle?",
  "Mitochondria",
  "A stethoscope?",
  "Something angry",
  "A sneeze?"
 ],
 "waves": [
  {
   "L": "Annoying",
   "R": "Deadly tonight",
   "ex": [
    [
     "Seborrheic keratosis",
     3
    ],
    [
     "Tension headache",
     8
    ],
    [
     "Gout flare",
     28
    ],
    [
     "Kidney stone",
     40
    ],
    [
     "Pneumonia",
     58
    ],
    [
     "Pulmonary embolism",
     86
    ],
    [
     "Hyperkalemia, K 7.2",
     90
    ],
    [
     "Aortic dissection",
     97
    ]
   ]
  },
  {
   "L": "Rare",
   "R": "Every clinic day",
   "ex": [
    [
     "Pheochromocytoma",
     4
    ],
    [
     "Addison disease",
     8
    ],
    [
     "Myasthenia gravis",
     14
    ],
    [
     "Celiac disease",
     40
    ],
    [
     "Gout",
     62
    ],
    [
     "Asthma",
     80
    ],
    [
     "Type 2 diabetes",
     94
    ],
    [
     "Hypertension",
     98
    ]
   ]
  },
  {
   "L": "Comes on over years",
   "R": "Over minutes",
   "ex": [
    [
     "Osteoporosis",
     3
    ],
    [
     "Hashimoto thyroiditis",
     8
    ],
    [
     "Type 2 diabetes",
     10
    ],
    [
     "Rheumatoid arthritis",
     25
    ],
    [
     "Pneumonia",
     60
    ],
    [
     "Septic shock",
     72
    ],
    [
     "Stroke",
     94
    ],
    [
     "Anaphylaxis",
     98
    ]
   ]
  },
  {
   "L": "Gentle drug",
   "R": "Black box warning",
   "ex": [
    [
     "Loratadine",
     5
    ],
    [
     "Acetaminophen at a normal dose",
     15
    ],
    [
     "Metformin",
     25
    ],
    [
     "Lisinopril",
     30
    ],
    [
     "Warfarin",
     75
    ],
    [
     "Fluoroquinolones",
     78
    ],
    [
     "Amiodarone",
     86
    ],
    [
     "Clozapine",
     92
    ]
   ]
  },
  {
   "L": "Easy to spell",
   "R": "Impossible to spell",
   "ex": [
    [
     "Gout",
     2
    ],
    [
     "Asthma",
     20
    ],
    [
     "Esophagus",
     45
    ],
    [
     "Diarrhea",
     55
    ],
    [
     "Pheochromocytoma",
     88
    ],
    [
     "Sphygmomanometer",
     96
    ]
   ]
  },
  {
   "L": "Boring to learn",
   "R": "Fascinating",
   "ex": [
    [
     "The Krebs cycle",
     12
    ],
    [
     "The coagulation cascade",
     25
    ],
    [
     "Vitamins",
     40
    ],
    [
     "Prions",
     88
    ],
    [
     "Phantom limb",
     92
    ]
   ]
  },
  {
   "L": "Cheap",
   "R": "Breaks the bank",
   "ex": [
    [
     "Aspirin",
     2
    ],
    [
     "Generic metformin",
     5
    ],
    [
     "An X-ray",
     22
    ],
    [
     "An MRI",
     65
    ],
    [
     "Insulin, without insurance",
     72
    ],
    [
     "Biologics",
     94
    ]
   ]
  },
  {
   "L": "Feels fine",
   "R": "Worst pain of your life",
   "ex": [
    [
     "High blood pressure",
     3
    ],
    [
     "Mild anemia",
     8
    ],
    [
     "Shingles",
     68
    ],
    [
     "Kidney stone",
     88
    ],
    [
     "Subarachnoid hemorrhage",
     97
    ]
   ]
  }
 ],
 "links": {
  "potassium": [
   "Digoxin",
   "Spironolactone",
   "Loop diuretics",
   "Thiazides",
   "Addison disease",
   "ACE inhibitors",
   "Calcium gluconate"
  ],
  "calcium": [
   "Thiazides",
   "Loop diuretics",
   "Lambert-Eaton syndrome",
   "Calcium gluconate",
   "Tetracyclines",
   "Hyperparathyroidism"
  ],
  "autoimmune": [
   "Graves disease",
   "Hashimoto thyroiditis",
   "Type 1 diabetes",
   "Myasthenia gravis",
   "Rheumatoid arthritis",
   "Addison disease"
  ],
  "thyroid": [
   "Graves disease",
   "Hashimoto thyroiditis",
   "Amiodarone",
   "Lithium",
   "Levothyroxine"
  ],
  "lung": [
   "Asthma",
   "COPD",
   "Amiodarone",
   "SIADH",
   "Lambert-Eaton syndrome",
   "Pneumonia"
  ],
  "kidney": [
   "Nephrotic syndrome",
   "Nephritic syndrome",
   "Aminoglycosides",
   "Lithium",
   "ACE inhibitors",
   "Diabetes insipidus"
  ],
  "heart": [
   "Digoxin",
   "Aortic stenosis",
   "Mitral stenosis",
   "Beta blockers",
   "Amiodarone",
   "Rheumatic fever"
  ],
  "insulin": [
   "Type 1 diabetes",
   "Type 2 diabetes",
   "Metformin",
   "GLP-1"
  ],
  "water": [
   "SIADH",
   "Diabetes insipidus",
   "Loop diuretics",
   "Thiazides",
   "Lithium"
  ],
  "ears": [
   "Loop diuretics",
   "Aminoglycosides"
  ],
  "cough": [
   "ACE inhibitors",
   "Asthma",
   "COPD",
   "Pneumonia"
  ],
  "bowel": [
   "Crohn disease",
   "Ulcerative colitis"
  ],
  "strep": [
   "Rheumatic fever",
   "Nephritic syndrome"
  ],
  "antibiotic": [
   "Vancomycin",
   "Aminoglycosides",
   "Rifampin",
   "Metronidazole",
   "Tetracyclines",
   "Fluoroquinolones"
  ],
  "tuberculosis": [
   "Rifampin",
   "Isoniazid"
  ],
  "pregnancy": [
   "Tetracyclines",
   "ACE inhibitors",
   "Warfarin",
   "Lithium"
  ],
  "bleeding": [
   "Warfarin",
   "Heparin",
   "Aspirin",
   "Iron deficiency anemia"
  ],
  "anemia": [
   "Iron deficiency anemia",
   "B12 deficiency"
  ],
  "nerves": [
   "B12 deficiency",
   "Isoniazid",
   "Myasthenia gravis",
   "Lambert-Eaton syndrome",
   "Vitamin B6"
  ],
  "cortisol": [
   "Cushing syndrome",
   "Addison disease",
   "Prednisone"
  ],
  "joints": [
   "Osteoarthritis",
   "Rheumatoid arthritis",
   "Fluoroquinolones",
   "Gout"
  ],
  "valve": [
   "Aortic stenosis",
   "Mitral stenosis",
   "Rheumatic fever"
  ]
 }
};
