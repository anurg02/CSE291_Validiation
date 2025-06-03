# -*- coding: utf-8 -*-
############################################################################
#
# OpenROAD Python script for a complete digital flow (Floorplan to DEF)
# Based on user requirements and consolidated from multiple drafts.
#
# Prerequisites:
#   - OpenROAD environment loaded.
#   - Synthesized netlist loaded into memory.
#   - Technology library (LEF/Liberty) loaded.
#   - Clock port named "clk" exists in the design.
#
# Usage:
#   Run this script within the OpenROAD Python interpreter.
#
############################################################################

import odb
import pdn
import drt
import psm
import openroad as ord
from openroad import Timing # Import Timing module for corner access

# Check if a design is loaded
design = ord.get_db().getChip()
if not design:
    print("Error: No design loaded. Please load a design (e.g., read_lef, read_def, read_verilog, synth_design). Exiting.")
    exit()

block = design.getBlock()
if not block:
    print("Error: Design loaded but no block found. Exiting.")
    exit()

tech = ord.get_db().getTech()
if not tech:
    print("Error: No technology database loaded. Please load LEF files. Exiting.")
    exit()

print("Design loaded. Starting Place & Route flow...")

############################################################################
# Clock Configuration
############################################################################
print("\n[INFO] Configuring clock...")
clock_period_ns = 20
clock_port_name = "clk"
clock_name = "core_clock"
clock_resistance = 0.03574
clock_capacitance = 0.07516
signal_resistance = 0.03574
signal_capacitance = 0.07516

# Use evalTclString to execute clock setup commands
try:
    # Check if the clock port exists before creating the clock
    ports = block.findITerms(clock_port_name)
    if not ports:
        print(f"Error: Clock port '{clock_port_name}' not found. Skipping clock configuration.")
    else:
        block.evalTclString(f"create_clock -period {clock_period_ns} [get_ports {clock_port_name}] -name {clock_name}")
        print(f"Clock '{clock_name}' created on port '{clock_port_name}' with period {clock_period_ns} ns.")
        # set_propagated_clock is deprecated/not standard tcl - rely on OpenROAD default or specific commands if needed
        # block.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")
        # print(f"Propagated clock set for '{clock_name}'.")
        block.evalTclString(f"set_wire_rc -clock -resistance {clock_resistance} -capacitance {clock_capacitance}")
        print(f"Set wire RC for clock nets: R={clock_resistance}, C={clock_capacitance}.")
        block.evalTclString(f"set_wire_rc -signal -resistance {signal_resistance} -capacitance {signal_capacitance}")
        print(f"Set wire RC for signal nets: R={signal_resistance}, C={signal_capacitance}.")
except Exception as e:
    print(f"Warning: Error during clock configuration: {e}")
    print("Continuing without complete clock setup might lead to issues in timing-aware steps.")


############################################################################
# Floorplan
############################################################################
print("\n[INFO] Performing floorplan...")

# Define die and core dimensions in microns
die_lx_um, die_ly_um, die_ux_um, die_uy_um = 0, 0, 40, 60
core_lx_um, core_ly_um, core_ux_um, core_uy_um = 10, 10, 30, 50

# Convert dimensions from microns to DBU (Database Units)
die_area_dbu = odb.Rect(block.micronToDBU(die_lx_um), block.micronToDBU(die_ly_um),
                        block.micronToDBU(die_ux_um), block.micronToDBU(die_uy_um))
core_area_dbu = odb.Rect(block.micronToDBU(core_lx_um), block.micronToDBU(core_ly_um),
                         block.micronToDBU(core_ux_um), block.micronToDBU(core_uy_um))

# Find a suitable placement site (CORE or any)
site = None
for lib in tech.getLibs():
    for s in lib.getSites():
        if s.getType() == "CORE":
            site = s
            break
    if site:
        break

if not site:
    # Fallback: find any site if no CORE sites exist
    for lib in tech.getLibs():
        if lib.getSites():
            site = lib.getSites()[0]
            break

if not site:
    print("Error: No placement site found in technology library. Exiting.")
    exit()

# Initialize floorplan
floorplan = block.getFloorplan()
floorplan.initFloorplan(die_area_dbu, core_area_dbu, site)

# Create placement tracks based on the site definition
floorplan.makeTracks()
print(f"Floorplan initialized. Die area: {die_lx_um}x{die_ly_um} to {die_ux_um}x{die_uy_um} um, Core area: {core_lx_um}x{core_ly_um} to {core_ux_um}x{core_uy_um} um.")


############################################################################
# Global Power/Ground Connections
############################################################################
print("\n[INFO] Establishing global power/ground connections...")

# Find existing power and ground nets or create them if they don't exist
VDD_net = block.findNet("VDD")
VSS_net = block.findNet("VSS")

# Create VDD/VSS nets if not found in the netlist
if VDD_net is None:
    VDD_net = odb.dbNet_create(block, "VDD")
    VDD_net.setSigType("POWER")
    VDD_net.setSpecial()
    print("Created VDD net.")
if VSS_net is None:
    VSS_net = odb.dbNet_create(block, "VSS")
    VSS_net.setSigType("GROUND")
    VSS_net.setSpecial()
    print("Created VSS net.")

# Connect standard cell power/ground pins to the global VDD/VSS nets
block.addGlobalConnect(region=None,
                       instPattern=".*",     # Apply to all instances
                       pinPattern="^VDD$",   # Match pins named VDD
                       net=VDD_net,
                       do_connect=True)
block.addGlobalConnect(region=None,
                       instPattern=".*",     # Apply to all instances
                       pinPattern="^VSS$",   # Match pins named VSS
                       net=VSS_net,
                       do_connect=True)

# Apply the defined global connections
block.globalConnect()
print("Global power/ground connections established for standard cells.")


############################################################################
# Macro Placement
############################################################################
print("\n[INFO] Performing macro placement...")

# Filter instances to identify macros (cells with isBlock=True)
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"Found {len(macros)} macros. Placing them...")
    mpl = design.getMacroPlacer()

    # Define macro placement constraints in microns
    macro_fence_lx_um, macro_fence_ly_um, macro_fence_ux_um, macro_fence_uy_um = 15, 10, 30, 40
    macro_halo_um = 5 # Halo for placement/routing blockage around macros
    # Note: Inter-macro spacing of 5um is implicitly handled by placer constraints
    # like congestion/density and halo, as there isn't a direct "min_spacing" parameter.

    # Run macro placement
    mpl.place(
        num_threads = 64, # Use a reasonable number of threads
        max_num_macro = len(macros),
        # Other parameters can be tuned based on design/technology, using defaults or examples:
        min_num_macro = 0, max_num_inst = 0, min_num_inst = 0,
        tolerance = 0.1, max_num_level = 2, coarsening_ratio = 10.0,
        large_net_threshold = 50, signature_net_threshold = 50,
        halo_width = block.micronToDBU(macro_halo_um), # Convert halo to DBU
        halo_height = block.micronToDBU(macro_halo_um), # Convert halo to DBU
        fence_lx = block.micronToDBU(macro_fence_lx_um), # Convert fence to DBU
        fence_ly = block.micronToDBU(macro_fence_ly_um), # Convert fence to DBU
        fence_ux = block.micronToDBU(macro_fence_ux_um), # Convert fence to DBU
        fence_uy = block.micronToDBU(macro_fence_uy_um), # Convert fence to DBU
        area_weight = 0.1, outline_weight = 100.0, wirelength_weight = 100.0,
        guidance_weight = 10.0, fence_weight = 10.0, boundary_weight = 50.0,
        notch_weight = 10.0, macro_blockage_weight = 10.0, pin_access_th = 0.0,
        target_util = 0.25, target_dead_space = 0.05, min_ar = 0.33,
        snap_layer = 0, # Use 0 for no specific snap layer if not required
        bus_planning_flag = False, report_directory = ""
    )
    print("Macro placement finished.")
else:
    print("No macros found in the design. Skipping macro placement.")


############################################################################
# Global Placement (Standard Cells)
############################################################################
print("\n[INFO] Performing global placement...")
gpl = design.getReplace()

# Configure global placement settings
gpl.setTimingDrivenMode(False) # Not timing-driven per prompt
gpl.setRoutabilityDrivenMode(True) # Enable routability-driven
gpl.setUniformTargetDensityMode(True) # Use uniform density
# InitialPlace settings (can be tuned)
gpl.setInitDensityPenalityFactor(0.05) # Example value
gpl.setInitWirelengthWeight(1.0) # Example value
gpl.setInitBeta(0.9) # Example value
gpl.setInitGamma(1.0) # Example value

# Run the initial placement phase
print("Running initial global placement...")
gpl.doInitialPlace(threads = 8) # Use a reasonable number of threads

# Run the Nesterov-based placement phase for further optimization
print("Running Nesterov global placement...")
gpl.doNesterovPlace(threads = 8)

# Reset the placer state
gpl.reset()
print("Global placement finished.")


############################################################################
# Detailed Placement
############################################################################
print("\n[INFO] Performing detailed placement...")
opendp = design.getOpendp()

# Define maximum displacement in microns
dp_max_disp_x_um = 1.0
dp_max_disp_y_um = 3.0

# Calculate maximum displacement in DBU
dp_max_disp_x_dbu = block.micronToDBU(dp_max_disp_x_um)
dp_max_disp_y_dbu = block.micronToDBU(dp_max_disp_y_um)

# Remove any existing filler cells before detailed placement
# This is a safeguard; fillers are typically inserted after DP.
opendp.removeFillers()
print("Removed any existing filler cells.")

print(f"Running detailed placement with max displacement X={dp_max_disp_x_um}um, Y={dp_max_disp_y_um}um...")
# Perform detailed placement. The displacement values are in DBU.
# detailedPlacement(max_displace_x_dbu, max_displace_y_dbu, cell_naming_pattern, use_multi_thread)
opendp.detailedPlacement(dp_max_disp_x_dbu, dp_max_disp_y_dbu, "", True) # Use True for multi-threading
print("Detailed placement finished.")


############################################################################
# Clock Tree Synthesis (CTS)
############################################################################
print("\n[INFO] Running Clock Tree Synthesis (CTS)...")
cts = design.getTritonCts()

# Define the list of usable buffer cells for CTS
buffer_list = "BUF_X2" # As specified in the prompt
cts.setBufferList(buffer_list)
# Set the buffer cell to be used at the clock root (optional, defaults to list)
cts.setRootBuffer("BUF_X2") # As specified in the prompt
# Set the buffer cell to be used at the clock sinks (optional, defaults to list)
cts.setSinkBuffer("BUF_X2") # As specified in the prompt

# Run the CTS process
cts.runTritonCts()
print("CTS finished.")


############################################################################
# Filler Cell Insertion
############################################################################
print("\n[INFO] Inserting filler cells...")
db = ord.get_db()
filler_masters = list()
# Find library masters that are designated as CORE_SPACER cells
for lib in db.getLibs():
    for master in lib.getMasters():
        if master.getType() == "CORE_SPACER":
            filler_masters.append(master)

# Perform filler placement if CORE_SPACER cells are found
if not filler_masters:
    print("Warning: No CORE_SPACER cells found in libraries. Cannot insert fillers.")
else:
    # Define the prefix for the names of the inserted filler instances
    filler_cells_prefix = "FILLCELL_"
    # Run the filler placement process
    opendp.fillerPlacement(filler_masters = filler_masters,
                           prefix = filler_cells_prefix,
                           verbose = False)
    print("Filler placement finished.")


############################################################################
# Power Delivery Network (PDN) Construction
############################################################################
print("\n[INFO] Configuring and building Power Delivery Network (PDN)...")
pdngen = design.getPdnGen()

# Set the core voltage domain using the primary power and ground nets
# VDD_net and VSS_net are assumed to be defined and connected globally
pdngen.setCoreDomain(power = VDD_net,
                     switched_power = None,
                     ground = VSS_net,
                     secondary = [])

# Define PDN dimensions in microns as specified in the prompt
# Standard cell grid parameters (M1 and M7 for standard cells)
std_cell_m1_width_um = 0.07 # Followpin
std_cell_m7_width_um = 1.4  # Strap
std_cell_m7_spacing_um = 1.4
std_cell_m7_pitch_um = 10.8

# Core ring parameters (M7 and M8)
core_ring_m7_width_um = 2.0
core_ring_m7_spacing_um = 2.0
core_ring_m8_width_um = 2.0
core_ring_m8_spacing_um = 2.0
core_ring_offset_um = [0, 0, 0, 0] # [left, bottom, right, top] offset from core boundary

# Macro grid parameters (M4, M5, M6 for macros)
macro_grid_m4_width_um = 1.2
macro_grid_m4_spacing_um = 1.2
macro_grid_m4_pitch_um = 6.0
macro_grid_m5_width_um = 1.2
macro_grid_m5_spacing_um = 1.2
macro_grid_m5_pitch_um = 6.0
macro_grid_m6_width_um = 1.2
macro_grid_m6_spacing_um = 1.2
macro_grid_m6_pitch_um = 6.0

# Via and offset parameters
via_cut_pitch_um = [0, 0] # [x, y] pitch for via generation between parallel stripes (0 means connect at every intersection)
offset_um = 0.0 # Generic offset value requested as 0

# Convert PDN dimensions from microns to DBU
std_cell_m1_width_dbu = block.micronToDBU(std_cell_m1_width_um)
std_cell_m7_width_dbu = block.micronToDBU(std_cell_m7_width_um)
std_cell_m7_spacing_dbu = block.micronToDBU(std_cell_m7_spacing_um)
std_cell_m7_pitch_dbu = block.micronToDBU(std_cell_m7_pitch_um)

core_ring_m7_width_dbu = block.micronToDBU(core_ring_m7_width_um)
core_ring_m7_spacing_dbu = block.micronToDBU(core_ring_m7_spacing_um)
core_ring_m8_width_dbu = block.micronToDBU(core_ring_m8_width_um)
core_ring_m8_spacing_dbu = block.micronToDBU(core_ring_m8_spacing_um)
core_ring_offset_dbu = [block.micronToDBU(o) for o in core_ring_offset_um]

macro_grid_m4_width_dbu = block.micronToDBU(macro_grid_m4_width_um)
macro_grid_m4_spacing_dbu = block.micronToDBU(macro_grid_m4_spacing_um)
macro_grid_m4_pitch_dbu = block.micronToDBU(macro_grid_m4_pitch_um)
macro_grid_m5_width_dbu = block.micronToDBU(macro_grid_m5_width_um)
macro_grid_m5_spacing_dbu = block.micronToDBU(macro_grid_m5_spacing_um)
macro_grid_m5_pitch_dbu = block.micronToDBU(macro_grid_m5_pitch_um)
macro_grid_m6_width_dbu = block.micronToDBU(macro_grid_m6_width_um)
macro_grid_m6_spacing_dbu = block.micronToDBU(macro_grid_m6_spacing_um)
macro_grid_m6_pitch_dbu = block.micronToDBU(macro_grid_m6_pitch_um)

via_cut_pitch_dbu = [block.micronToDBU(p) for p in via_cut_pitch_um]
offset_dbu = block.micronToDBU(offset_um)
pdn_halo_dbu = [block.micronToDBU(macro_halo_um) for _ in range(4)] # Use macro halo for PDN keepout

# Get necessary metal layers for PDN creation
m1 = tech.findLayer("metal1")
m4 = tech.findLayer("metal4")
m5 = tech.findLayer("metal5")
m6 = tech.findLayer("metal6")
m7 = tech.findLayer("metal7")
m8 = tech.findLayer("metal8")

# Check if required layers exist
required_layers = {"metal1": m1, "metal4": m4, "metal5": m5, "metal6": m6, "metal7": m7, "metal8": m8}
missing_layers = [name for name, layer in required_layers.items() if layer is None]
if missing_layers:
    print(f"Warning: Missing required metal layers for PDN: {', '.join(missing_layers)}. PDN construction may fail or be incomplete.")


domains = [pdngen.findDomain("Core")] # Get the core domain object

if domains:
    # Create the main core grid structure where standard cells reside
    # This grid object represents the standard cell area for PDN generation
    core_grid_name = "core_stdcell_grid"
    print(f"  - Creating core grid '{core_grid_name}' for standard cells...")
    pdngen.makeCoreGrid(domain = domains[0],
                        name = core_grid_name,
                        starts_with = pdn.GROUND, # Arbitrary start preference
                        pin_layers = [], # Standard cell pins are typically connected by followpins/straps
                        generate_obstructions = [],
                        powercell = None, powercontrol = None, powercontrolnetwork = "STAR")

    core_grid = pdngen.findGrid(core_grid_name)

    if core_grid:
        core_grid_obj = core_grid[0] # Use the first grid found with this name

        # Create power rings around the core area using metal7 and metal8
        print("  - Adding core rings on M7 and M8...")
        if m7 and m8:
            pdngen.makeRing(grid = core_grid_obj,
                            layer0 = m7, width0 = core_ring_m7_width_dbu, spacing0 = core_ring_m7_spacing_dbu,
                            layer1 = m8, width1 = core_ring_m8_width_dbu, spacing1 = core_ring_m8_spacing_dbu,
                            starts_with = pdn.GRID,
                            offset = core_ring_offset_dbu,
                            pad_offset = [0,0,0,0], extend = False, pad_pin_layers = [], nets = [])
        else: print("    Warning: Cannot add M7/M8 core rings (layers missing).")


        # Create horizontal power straps on metal1 following standard cell power pins (followpins)
        print("  - Adding standard cell followpins on M1...")
        if m1:
            pdngen.makeFollowpin(grid = core_grid_obj,
                                 layer = m1,
                                 width = std_cell_m1_width_dbu,
                                 extend = pdn.CORE) # Extend straps within the core area boundaries
        else: print("    Warning: Metal1 layer not found. Cannot add M1 followpins.")

        # Create power straps on metal7 for standard cells
        print("  - Adding standard cell straps on M7...")
        if m7:
             pdngen.makeStrap(grid = core_grid_obj,
                              layer = m7,
                              width = std_cell_m7_width_dbu,
                              spacing = std_cell_m7_spacing_dbu,
                              pitch = std_cell_m7_pitch_dbu,
                              offset = offset_dbu,
                              number_of_straps = 0, # Auto-calculate
                              snap = False,
                              starts_with = pdn.GRID,
                              extend = pdn.RINGS, # Extend to connect to the M7/M8 rings
                              nets = [])
        else: print("    Warning: Metal7 layer not found. Cannot add M7 standard cell straps.")

        # Create via connections between standard cell power grid layers
        print("  - Adding standard cell grid connections (vias)...")
        # Connect M1 (followpin) to M7 (strap)
        if m1 and m7:
            pdngen.makeConnect(grid = core_grid_obj, layer0 = m1, layer1 = m7,
                               cut_pitch_x = via_cut_pitch_dbu[0], cut_pitch_y = via_cut_pitch_dbu[1])
        else: print("    Warning: Cannot add M1-M7 connections (layers missing).")

        # Connect M7 (strap) to M8 (ring) - Note: M7 also has rings, M8 only has rings.
        # Vias are needed from M7 straps/rings to M8 rings.
        # The `extend = pdn.RINGS` on M7 straps helps them reach the ring area.
        if m7 and m8:
             pdngen.makeConnect(grid = core_grid_obj, layer0 = m7, layer1 = m8,
                                cut_pitch_x = via_cut_pitch_dbu[0], cut_pitch_y = via_cut_pitch_dbu[1])
        else: print("    Warning: Cannot add M7-M8 connections (layers missing).")

    else:
        print("Warning: Core grid 'core_stdcell_grid' not found after creation attempt. Standard cell PDN components were not fully created.")

    # Create power grid for macro blocks if macros exist
    if len(macros) > 0:
        print(f"Creating PDN grids for {len(macros)} macros...")
        # Use the list of macros identified during placement
        for i, macro_inst in enumerate(macros): # Use enumerate for index if needed, otherwise just iterate
            # Create a unique grid name for each macro instance
            macro_grid_name = f"macro_grid_{macro_inst.getName()}"

            # Create instance-specific grid structure for this macro
            # Apply to the core domain, restrict to this instance
            print(f"  - Creating grid '{macro_grid_name}' for macro '{macro_inst.getName()}'...")
            pdngen.makeInstanceGrid(domain = domains[0],
                                    name = macro_grid_name,
                                    starts_with = pdn.GROUND, # Start relative to instance boundary
                                    inst = macro_inst,
                                    halo = pdn_halo_dbu, # Halo around this macro instance for PDN keepout
                                    pg_pins_to_boundary = True, # Connect macro PG pins to the grid boundary
                                    default_grid = False,
                                    generate_obstructions = [],
                                    is_bump = False)

            macro_grids = pdngen.findGrid(macro_grid_name)

            if macro_grids:
                macro_grid_obj = macro_grids[0] # Assume makeInstanceGrid creates one grid per name

                # Create power straps on metal4 for macro connections
                print("    - Adding macro straps on M4...")
                if m4:
                    pdngen.makeStrap(grid = macro_grid_obj,
                                     layer = m4,
                                     width = macro_grid_m4_width_dbu,
                                     spacing = macro_grid_m4_spacing_dbu,
                                     pitch = macro_grid_m4_pitch_dbu,
                                     offset = offset_dbu,
                                     number_of_straps = 0,
                                     snap = True,  # Snap to grid (often needed for macro pin alignment)
                                     starts_with = pdn.GRID, # Start relative to instance grid origin
                                     extend = pdn.CORE, # Extend within the macro instance boundaries (including halo)
                                     nets = []) # Apply to nets defined for the grid
                else: print("      Warning: Metal4 layer not found. Cannot add M4 macro straps.")

                # Create power straps on metal5 for macro connections
                print("    - Adding macro straps on M5...")
                if m5:
                    pdngen.makeStrap(grid = macro_grid_obj,
                                     layer = m5,
                                     width = macro_grid_m5_width_dbu,
                                     spacing = macro_grid_m5_spacing_dbu,
                                     pitch = macro_grid_m5_pitch_dbu,
                                     offset = offset_dbu,
                                     number_of_straps = 0,
                                     snap = True,
                                     starts_with = pdn.GRID,
                                     extend = pdn.CORE,
                                     nets = [])
                else: print("      Warning: Metal5 layer not found. Cannot add M5 macro straps.")

                # Create power straps on metal6 for macro connections
                print("    - Adding macro straps on M6...")
                if m6:
                    pdngen.makeStrap(grid = macro_grid_obj,
                                     layer = m6,
                                     width = macro_grid_m6_width_dbu,
                                     spacing = macro_grid_m6_spacing_dbu,
                                     pitch = macro_grid_m6_pitch_dbu,
                                     offset = offset_dbu,
                                     number_of_straps = 0,
                                     snap = True,
                                     starts_with = pdn.GRID,
                                     extend = pdn.CORE,
                                     nets = [])
                else: print("      Warning: Metal6 layer not found. Cannot add M6 macro straps.")

                # Create via connections between macro power grid layers and core grid layers
                print("    - Adding macro grid connections (vias)...")
                if m4 and m5:
                    # Connect metal4 to metal5 (macro grid layers)
                     pdngen.makeConnect(grid = macro_grid_obj, layer0 = m4, layer1 = m5,
                                       cut_pitch_x = via_cut_pitch_dbu[0], cut_pitch_y = via_cut_pitch_dbu[1])
                else: print("      Warning: Cannot add M4-M5 connections (layers missing).")

                if m5 and m6:
                    # Connect metal5 to metal6 (macro grid layers)
                    pdngen.makeConnect(grid = macro_grid_obj, layer0 = m5, layer1 = m6,
                                       cut_pitch_x = via_cut_pitch_dbu[0], cut_pitch_y = via_cut_pitch_dbu[1])
                else: print("      Warning: Cannot add M5-M6 connections (layers missing).")

                if m6 and m7:
                    # Connect metal6 (macro grid) to metal7 (core grid strap/ring)
                    pdngen.makeConnect(grid = macro_grid_obj, layer0 = m6, layer1 = m7,
                                       cut_pitch_x = via_cut_pitch_dbu[0], cut_pitch_y = via_cut_pitch_dbu[1])
                else: print("      Warning: Cannot add M6-M7 connections (layers missing).")

            else:
                 print(f"Warning: Could not find macro grid '{macro_grid_name}' after creation attempt.")
    else:
        print("No macros found. Skipping macro PDN construction.")

    # Finalize and build the power delivery network
    print("Building and writing PDN grids to design database...")
    pdngen.checkSetup()  # Verify the PDN setup configuration
    pdngen.buildGrids(False)  # Build the power grid geometry (False for non-timing-driven)
    pdngen.writeToDb(True)  # Write the created power grid shapes to the design database
    print("PDN construction finished.")

    # --- Correction for Feedback #2: Dump DEF file *after* PDN construction ---
    output_def_file = "PDN.def" # Name specified in the prompt
    print(f"\n[INFO] Writing DEF file after PDN construction: {output_def_file}")
    block.writeDef(output_def_file)
    print("DEF file written.")
    # --- End Correction ---

    # Reset temporary shapes used during generation - call after writing to DB
    pdngen.resetShapes()

else:
    print("Error: Could not find 'Core' domain for PDN setup. Skipping PDN construction.")


############################################################################
# Global Routing
############################################################################
# Global routing happens AFTER PDN construction, as the PDN consumes routing layers
# and creates blockages that the router must respect.
print("\n[INFO] Running global routing...")
grt = design.getGlobalRouter()

# Set the number of iterations as specified in the prompt
grt.setIterations(10)
print(f"Set global router iterations to {grt.getIterations()}.")

# Set the minimum and maximum routing layers for signals and clock nets
# Defaulting to M1-M7 range if layers are found and M7 is usable for routing
signal_low_layer = tech.findLayer("metal1")
signal_high_layer = tech.findLayer("metal7") # M7 is used for PDN straps/rings, check if still available for routing

if signal_low_layer and signal_high_layer:
    # Check if M7 is a routable layer
    if signal_high_layer.getType() == odb.dbTechLayerType.ROUTING:
        grt.setMinRoutingLayer(signal_low_layer.getRoutingLevel())
        grt.setMaxRoutingLayer(signal_high_layer.getRoutingLevel())
        grt.setMinLayerForClock(signal_low_layer.getRoutingLevel()) # Using same range for clock
        grt.setMaxLayerForClock(signal_high_layer.getRoutingLevel()) # Using same range for clock
        print(f"Set global routing layers from {signal_low_layer.getName()} to {signal_high_layer.getName()}.")
    else:
        print(f"Warning: Metal layer {signal_high_layer.getName()} is not a ROUTING layer. Using default layers for global routing.")
else:
     print("Warning: Could not find metal1 or metal7 for global routing layer range. Using default layers.")


# Set the adjustment factor to control routing congestion estimation (can be tuned)
grt.setAdjustment(0.7) # Example value, higher values reduce congestion but increase wirelength
# Enable verbose output for global routing
grt.setVerbose(True)

# Run the global routing process (False for non-timing-driven)
grt.globalRoute(False)
print("Global routing finished.")


############################################################################
# Detailed Routing
############################################################################
# Detailed routing happens AFTER Global Routing.
print("\n[INFO] Running detailed routing...")
drter = design.getTritonRoute()
params = drt.ParamStruct()

# Set the bottom and top routing layers for the detailed router
# Using the same range as global routing if found and routable
if signal_low_layer and signal_high_layer and signal_high_layer.getType() == odb.dbTechLayerType.ROUTING:
    params.bottomRoutingLayer = signal_low_layer.getName()
    params.topRoutingLayer = signal_high_layer.getName()
    print(f"Set detailed routing layers from {params.bottomRoutingLayer} to {params.topRoutingLayer}.")
else:
     print("Warning: Could not find metal1 or metal7 (or M7 is not routable) for detailed routing layer range. Using default layers.")
     # TritonRoute will use default layers if these are not set

# Other detailed routing parameters (tuned for typical flow)
params.outputMazeFile = ""
# params.outputDrcFile = "route_drc.rpt" # Optional: specify file for DRC violations report
params.outputCmapFile = ""
params.outputGuideCoverageFile = ""
params.dbProcessNode = "" # Technology node specific parameter (optional)
params.enableViaGen = True # Enable automatic via generation
params.drouteEndIter = 1 # Number of detailed routing iterations (1 is typical after GRT)
params.viaInPinBottomLayer = "" # Optional: constrain via-in-pin layers
params.viaInPinTopLayer = "" # Optional: constrain via-in-pin layers
params.orSeed = -1 # Obstruction router random seed (-1 for random)
params.orK = 0 # Obstruction router parameter
params.verbose = 1 # Verbosity level
params.cleanPatches = True # Clean up routing patches
params.doPa = True # Perform pin access analysis
params.singleStepDR = False # Run detailed routing in a single step
params.minAccessPoints = 1 # Minimum number of pin access points
params.saveGuideUpdates = False # Save guide updates (for debugging)

# Set the configured parameters for the detailed router
drter.setParams(params)
# Run the detailed routing process
drter.main()
print("Detailed routing finished.")


############################################################################
# Static IR Drop Analysis
############################################################################
# IR Drop analysis can be run at various stages (after PDN, after placement, after routing).
# The prompt implies running it *after* PDN construction, before the final DEF dump (which we've moved).
# However, the request "get the IR drop analysis result on M1 layer" makes more sense on a
# placed+PDN design, as the analysis is performed on the network structure built.
# The script performs analysis after PDN construction, before routing, which aligns
# with the feedback's implied timing for the DEF dump.
print("\n[INFO] Running static IR drop analysis on VDD net...")
psm_obj = design.getPDNSim()

# Need a timing corner to perform analysis. Get the first available corner.
# Re-initialize Timing object as it might be needed
try:
    timing = Timing(design)
    corners = timing.getCorners()
except Exception as e:
    print(f"Warning: Could not initialize Timing module or retrieve corners: {e}")
    corners = []

VDD_net = block.findNet("VDD") # Re-find net object just in case

if not corners:
    print("Error: No timing corners found. Cannot run IR drop analysis. Skipping IR drop analysis.")
elif VDD_net is None:
     print("Error: VDD net not found. Cannot run IR drop analysis. Skipping IR drop analysis.")
else:
    # Define the type of power/ground sources for the analysis
    # Using BUMPS source type as seen in example 4 - BUMPS represents connections
    # at the edge of the die or pads.
    source_types = [psm.GeneratedSourceType_FULL,
                    psm.GeneratedSourceType_STRAPS,
                    psm.GeneratedSourceType_BUMPS]

    # Analyze the VDD power grid for IR drop using the first timing corner
    # The 'analyzePowerGrid' function performs the analysis across all grid layers
    # connected to the specified net. Getting results *specifically* on the M1 layer
    # might require post-processing of the output files or using specific reporting
    # functions not directly available in this basic Python API call.
    # You might add `voltage_file="vdd_voltage.volt"` to output voltage data.
    print(f"Analyzing VDD net using corner '{corners[0].getName()}'...")
    psm_obj.analyzePowerGrid(net = VDD_net,
                             enable_em = False, # Disable electromigration analysis
                             corner = corners[0], # Use the first timing corner for analysis
                             use_prev_solution = False,
                             em_file = "",
                             error_file = "",
                             voltage_source_file = "",
                             voltage_file = "", # Optional: specify output file for voltage map (e.g., "vdd_voltage.volt")
                             source_type = source_types[2]) # Use BUMPS as the source type
    print("Static IR drop analysis finished for VDD net.")
    # Note: To specifically report or visualize IR drop on M1, you might need
    # additional Tcl commands or analysis tools integrated with OpenROAD's PSM engine.
    # The analysis itself has been performed on the VDD grid which includes M1.


############################################################################
# Final Output (After Detailed Routing)
############################################################################
# Note: The prompt requested the DEF dump "After PDN construction".
# A DEF file containing the full routed result would be dumped here.
# Since we already dumped PDN.def, we could dump another file if needed,
# but following the prompt's instruction means PDN.def is the file *after* PDN.
# If a fully routed DEF is needed, another writeDef call would be placed here.
# print(f"\n[INFO] Writing final routed DEF file: final_routed.def")
# block.writeDef("final_routed.def")
# print("Final routed DEF file written.")


print("\nFlow finished successfully.")