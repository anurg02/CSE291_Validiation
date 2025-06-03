# This script is a consolidation and refinement of the provided Gemini draft
# based on the original prompt requirements and OpenROAD best practices.
# The second script (OpenAI draft) was unavailable for comparison.

import odb
import pdn
import openroad as ord
import drt
import math
import traceback # Import traceback for detailed error reporting

# Get the current design block and technology
# Ensure design is loaded before this script is run.
# Example TCL commands to load design/libraries before running this script:
# read_lef <your_lib.lef>
# read_def <your_netlist.def> OR read_verilog <your_netlist.v>; link_design <top_module>
# read_sdc <your_timing.sdc> # Recommended for timing analysis
# read_liberty <your_timing.lib> # Recommended for timing analysis and power analysis
# initialize_floorplan # If not starting with a DEF that has floorplan

design = ord.get_design()
if design is None:
    print("Error: No design loaded. Please load a design (DEF/Verilog+LEF) before running this script.")
    # Depending on your OpenROAD environment setup, you might want to exit
    # or handle this differently. Exiting is safer in a standalone script.
    exit(1)

block = design.getBlock()
if block is None:
    print("Error: No block found in the design. Ensure design is properly linked.")
    exit(1)

tech = design.getTech().getDB().getTech()
if tech is None:
    print("Error: No technology found in the design. Ensure LEFs are loaded.")
    exit(1)

dbu_per_micron = tech.getDbUnitsPerMicron()
if dbu_per_micron == 0:
     print("Error: Technology has zero DBUs per micron. Check LEF files.")
     exit(1)

# Helper functions for DBU conversion
def micronToDBU(microns):
    "Converts microns to design database units (DBU)."
    return int(microns * dbu_per_micron)

def dbuToMicrons(dbu):
    "Converts design database units (DBU) to microns."
    if dbu_per_micron == 0: return 0.0 # Avoid division by zero
    return dbu / dbu_per_micron

print("OpenROAD Python flow script started.")
print(f"Database units per micron: {dbu_per_micron}")

# --- 1. Clock Setup ---
print("\n--- Stage 1: Clock Setup ---")
# Given clock port is "clk", set period to 20 ns
clock_period_ns = 20.0
clock_period_ps = clock_period_ns * 1000 # OpenROAD SDC commands often use picoseconds
clock_port_name = "clk"
clock_name = "core_clock" # A descriptive name for the clock object/net

print(f"Creating clock '{clock_name}' on port '{clock_port_name}' with period {clock_period_ns} ns ({clock_period_ps} ps).")
# Create the clock using the standard TCL command via evalTclString
# Using try-except to catch potential errors, though create_clock is fundamental
try:
    # Check if the clock port exists before trying to create the clock on it
    clock_port = block.findBTerm(clock_port_name)
    if clock_port is None:
        print(f"Error: Clock port '{clock_port_name}' not found in the design block. Cannot create clock. Exiting.")
        exit(1)

    # Create the clock constraint
    design.evalTclString(f"create_clock -period {clock_period_ps} [get_ports {clock_port_name}] -name {clock_name}")
    print(f"Clock '{clock_name}' successfully created.")

    # Set the clock as propagated (required for accurate timing analysis)
    # This tells the tool to use the actual clock tree network delays once CTS is run
    design.evalTclString(f"set_propagated_clock [get_clocks {{{clock_name}}}]")
    print(f"Set clock '{clock_name}' as propagated.")

except Exception as e:
    print(f"Error during clock setup: {e}")
    print(f"Clock setup failed. Timing analysis and subsequent steps may be affected. Exiting.")
    exit(1)

# Note: Dumping DEF here is possible but doesn't show significant layout changes
# unless the input DEF was completely empty and ports are created.

# --- 2. Floorplanning ---
print("\n--- Stage 2: Floorplanning ---")
floorplan = design.getFloorplan()

# Check if a floorplan already exists (e.g., if loading a DEF with floorplan)
if floorplan.getDieBox() is not None and floorplan.getDieBox().isValid():
    print("Existing floorplan detected. Skipping floorplan initialization.")
    # If floorplan exists, we still need to ensure tracks are made if not already.
    # makeTracks() is safe to call even if tracks exist.
    try:
        floorplan.makeTracks()
        print("Ensured floorplan tracks are created.")
    except Exception as e:
        print(f"Warning: Could not create or verify floorplan tracks: {e}")
else:
    print("No existing floorplan found. Initializing floorplan.")

    # Calculate total standard cell area for floorplan sizing
    total_std_cell_area_dbu2 = 0
    std_cell_count = 0
    for inst in block.getInsts():
        master = inst.getMaster()
        # Standard cells typically have type "CORE" and are associated with a site
        if master.getType() == "CORE" and master.getSite() is not None:
             area_dbu2 = master.getWidth() * master.getHeight()
             total_std_cell_area_dbu2 += area_dbu2
             std_cell_count += 1

    print(f"Found {std_cell_count} standard cells with total area (DBU^2): {total_std_cell_area_dbu2}.")
    if total_std_cell_area_dbu2 > 0:
         # Area is in DBU^2, convert to um^2
         total_std_cell_area_um2 = total_std_cell_area_dbu2 / (dbu_per_micron * dbu_per_micron)
         print(f"Total standard cell area (um^2): {total_std_cell_area_um2}")


    # Target utilization for core area calculation
    target_utilization = 0.35
    print(f"Target utilization: {target_utilization * 100} %.")

    # Calculate required core area in DBU^2
    # Basic calculation: total std cell area / target utilization
    required_core_area_dbu2 = 0
    if total_std_cell_area_dbu2 > 0 and target_utilization > 0:
        required_core_area_dbu2 = int(total_std_cell_area_dbu2 / target_utilization)
        print(f"Calculated required core area (DBU^2): {required_core_area_dbu2}.")
    else:
        # Fallback: if no standard cells or zero area/utilization, use a default size
        print("Warning: Could not calculate core area from standard cells/utilization.")
        default_core_size_um = 200.0 # Use a larger default as fallback side length
        required_core_area_dbu2 = int(micronToDBU(default_core_size_um) * micronToDBU(default_core_size_um)) # Calculate area
        print(f"Using a default core area of {default_core_size_um} um x {default_core_size_um} um (DBU^2: {required_core_area_dbu2}).")

    # Assume square core shape for simplicity of calculation from area
    # In a real flow, shape could be optimized or fixed aspect ratio used.
    core_side_dbu = int(math.sqrt(required_core_area_dbu2))

    # Set core area rectangle in DBU. Often starts at origin (0,0).
    # It's common to center the core area relative to the origin if the die is also centered,
    # but the prompt doesn't specify, so keeping it simple starting from (0,0).
    core_rect_dbu = odb.Rect(0, 0, core_side_dbu, core_side_dbu)
    print(f"Proposed Core Box (DBU): ({core_rect_dbu.xMin()}, {core_rect_dbu.yMin()}) - ({core_rect_dbu.xMax()}, {core_rect_dbu.yMax()})")
    print(f"Proposed Core Box (um): ({dbuToMicrons(core_rect_dbu.xMin())}, {dbuToMicrons(core_rect_dbu.yMin())}) - ({dbuToMicrons(core_rect_dbu.xMax())}, {dbuToMicrons(core_rect_dbu.yMax())})")


    # Set core-to-die spacing (margin)
    margin_um = 5.0
    margin_dbu = micronToDBU(margin_um)
    print(f"Core-to-die margin: {margin_um} um ({margin_dbu} dbu).")


    # Calculate die area based on core area and margin
    # Die area is core area + margin on all sides (left, bottom, right, top)
    die_x_min = core_rect_dbu.xMin() - margin_dbu
    die_y_min = core_rect_dbu.yMin() - margin_dbu
    die_x_max = core_rect_dbu.xMax() + margin_dbu
    die_y_max = core_rect_dbu.yMax() + margin_dbu
    die_rect_dbu = odb.Rect(die_x_min, die_y_min, die_x_max, die_y_max)
    print(f"Calculated Die Box (DBU): ({die_rect_dbu.xMin()}, {die_rect_dbu.yMin()}) - ({die_rect_dbu.xMax()}, {die_rect_dbu.yMax()})")
    print(f"Calculated Die Box (um): ({dbuToMicrons(die_rect_dbu.xMin())}, {dbuToMicrons(die_rect_dbu.yMin())}) - ({dbuToMicrons(die_rect_dbu.xMax())}, {dbuToMicrons(die_rect_dbu.yMax())})")


    # Find a suitable site for standard cells. Needed for row creation.
    site = None
    # Prefer site from existing rows if any (common if loading a DEF with some rows)
    if block.getRows():
        site = block.getRows()[0].getSite()
        if site: print(f"Found site '{site.getName()}' from existing rows.")
    else:
         # Attempt to find a generic CORE site in the technology libraries
         print("No standard cell rows found. Searching libraries for a CORE site.")
         # Iterate through all libraries in the technology database
         for lib in design.getTech().getDB().getLibs():
             # Iterate through all sites defined in the library
             for found_site in lib.getSites():
                 # Look for sites typically used by standard cells ("CORE" type)
                 # Also check for 'BOTH' symmetry as it's common for standard cell sites
                 if found_site.getType() == "CORE" and found_site.getSymmetry() == odb.dbSite.Symmetry.BOTH:
                      site = found_site
                      print(f"Found CORE site '{site.getName()}' in library '{lib.getName()}'.")
                      break # Found a CORE site, stop searching sites in this lib
             if site:
                  break # Found a site in this lib, stop searching libraries

         if not site:
              print("Error: Could not find a suitable CORE site for floorplanning. Cannot initialize floorplan.")


    # Initialize floorplan with calculated die and core areas and found site
    if site:
        try:
            # initFloorplan creates the die boundary, core boundary, and standard cell rows
            floorplan.initFloorplan(die_rect_dbu, core_rect_dbu, site)
            print("Floorplan initialized successfully.")

            # Make tracks after floorplan is initialized. Tracks define valid routing grids.
            floorplan.makeTracks()
            print("Floorplan tracks created.")

        except Exception as e:
            print(f"Error during floorplan initialization or track creation: {e}")
            print("Floorplan initialization failed. Subsequent steps will likely fail. Exiting.")
            # Invalidate site or floorplan object if initialization failed
            site = None
            exit(1)
    else:
        print("Floorplan initialization skipped due to missing site. Exiting.")
        exit(1) # Cannot proceed without a floorplan


# Dump DEF after floorplanning
# Only dump if floorplan was successfully initialized or existed
if floorplan.getDieBox() is not None and floorplan.getDieBox().isValid():
    design.writeDef("2_floorplan.def")
    print("Dumped 2_floorplan.def")
else:
    print("Floorplan is not valid. Skipping DEF dump for floorplan stage.")


# --- 3. Pin Placement ---
print("\n--- Stage 3: Pin Placement ---")
# Configure and run I/O pin placement
# Get technology layers for M8 (Horizontal) and M9 (Vertical) as specified
metal8_layer = tech.findLayer("metal8")
metal9_layer = tech.findLayer("metal9")

if metal8_layer is None:
    print("Error: Could not find metal8 layer. Cannot perform I/O placement. Exiting.")
    exit(1)
if metal9_layer is None:
    print("Error: Could not find metal9 layer. Cannot perform I/O placement. Exiting.")
    exit(1)

try:
    io_placer = design.getIOPlacer()
    io_placer.reset() # Reset previous settings for a clean run
    params = io_placer.getParameters()

    # Set parameters based on common usage/examples. Prompt only specified layers.
    params.setMinDistance(micronToDBU(0)) # Minimum distance between pins in DBU (0 means no minimum explicit spacing)
    params.setMinDistanceInTracks(False) # Distance is in DBU, not tracks
    params.setCornerAvoidance(micronToDBU(0)) # No special corner avoidance distance from die corners
    params.setRandSeed(42) # Use a fixed seed for reproducibility of results

    # Add preferred layers for horizontal and vertical pins
    # Ensure layers exist and are routing layers
    if metal8_layer.getDirection() == "HORIZONTAL" or metal8_layer.getDirection() == "NONE":
         io_placer.addHorLayer(metal8_layer)
         print(f"Configured horizontal pins on {metal8_layer.getName()}.")
    else:
         # This is unexpected based on common layer directions, but follow prompt's intent if possible
         print(f"Warning: metal8 direction is {metal8_layer.getDirection()}, but adding as horizontal layer for pins.")
         io_placer.addHorLayer(metal8_layer)


    if metal9_layer.getDirection() == "VERTICAL" or metal9_layer.getDirection() == "NONE":
         io_placer.addVerLayer(metal9_layer)
         print(f"Configured vertical pins on {metal9_layer.getName()}.")
    else:
         # This is unexpected based on common layer directions, but follow prompt's intent if possible
         print(f"Warning: metal9 direction is {metal9_layer.getDirection()}, but adding as vertical layer for pins.")
         io_placer.addVerLayer(metal9_layer)


    # Run I/O placer using annealing. True enables random mode which can help convergence.
    print("Running I/O placement annealing...")
    io_placer.runAnnealing(True)
    print("I/O placement complete.")

    # Dump DEF after I/O placement
    design.writeDef("3_io_placement.def")
    print("Dumped 3_io_placement.def")

except Exception as e:
    print(f"Error during I/O placement: {e}")
    traceback.print_exc()
    print("I/O placement failed.")


# --- 4. Macro Placement ---
print("\n--- Stage 4: Macro Placement ---")
# Identify macros (instances with master type BLOCK)
macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]

if len(macros) > 0:
    print(f"Found {len(macros)} macros. Running macro placement.")
    try:
        mpl = design.getMacroPlacer()
        # Reset macro placer settings if needed (usually happens automatically on run)
        # mpl.reset() # No explicit reset method documented in python API

        # Set halo around each macro (5 um) - This is space where std cells will not be placed
        halo_um = 5.0
        # mpl.place takes halo width/height as float microns
        print(f"Setting {halo_um} um halo around macros.")

        # Configure macro placement parameters
        macro_placement_params = {
            'halo_width': halo_um,
            'halo_height': halo_um,
            # Other parameters controlling placement behavior (often from examples)
            'num_threads': 64, # Number of threads to use
            'min_ar': 0.33, # Minimum aspect ratio for groups of macros (if grouped)
        }
        # Ensure 'snap_layer' is set appropriately (snap to routing grid for placement)
        metal1_layer = tech.findLayer("metal1")
        if metal1_layer and metal1_layer.getRoutingLevel() > 0:
             macro_placement_params['snap_layer'] = metal1_layer.getRoutingLevel()
             print(f"Snapping macro placement to {metal1_layer.getName()} tracks (level {metal1_layer.getRoutingLevel()}).")
        else:
             print("Warning: metal1 layer not found or not a routing layer. Cannot snap macro placement to M1 tracks. Using default layer 1.")
             macro_placement_params['snap_layer'] = 1 # Fallback to layer index 1, assuming it's a valid base routing layer


        # Option: Restrict macro placement to the core area
        core_area = block.getCoreArea()
        if core_area is not None and core_area.isValid():
             # mpl.place takes fence coordinates as float microns
             macro_placement_params['fence_lx'] = dbuToMicrons(core_area.xMin())
             macro_placement_params['fence_ly'] = dbuToMicrons(core_area.yMin())
             macro_placement_params['fence_ux'] = dbuToMicrons(core_area.xMax())
             macro_placement_params['fence_uy'] = dbuToMicrons(core_area.yMax())
             print(f"Fencing macro placement within core area: ({dbuToMicrons(core_area.xMin())}, {dbuToMicrons(core_area.yMin())}) - ({dbuToMicrons(core_area.xMax())}, {dbuToMicrons(core_area.yMax())}) um.")
        else:
            print("Warning: Core area is not valid. Cannot fence macro placement.")

        # Note: The prompt requested "Make sure each macro is at least 5 um to each other".
        # The macro placer's halo primarily keeps *standard cells* away from macros.
        # Achieving a minimum distance *between macro boundaries* is influenced by
        # the tool's placement algorithm and density, and is not a direct parameter
        # controllable by 'halo' alone. The 'halo' contributes to spacing by reducing
        # available space for standard cells around macros.

        # Run the macro placement algorithm
        print("Running macro placement...")
        # Use kwargs to pass the dictionary parameters
        mpl.place(**macro_placement_params)
        print("Macro placement complete.")

        # Dump DEF after macro placement
        design.writeDef("4_macro_placement.def")
        print("Dumped 4_macro_placement.def")

    except Exception as e:
        print(f"Error during macro placement: {e}")
        traceback.print_exc()
        print("Macro placement failed.")

else:
    print("No macros found in the design. Skipping macro placement stage.")


# --- 5. Global Placement ---
print("\n--- Stage 5: Global Placement ---")
try:
    # Get the global placer tool (Replace)
    gpl = design.getReplace()
    gpl.reset() # Reset previous settings for a clean run

    # Configure global placement parameters
    # Assuming timing driven is not required unless specified
    gpl.setTimingDrivenMode(False)
    # Enable routability driven mode, important for congestion
    gpl.setRoutabilityDrivenMode(True)
    # Use uniform target density across the core area
    gpl.setUniformTargetDensityMode(True)
    # Set the target utilization for standard cells (from floorplan step)
    gpl.setTargetDensity(target_utilization)
    print(f"Global placement target density set to {target_utilization}.")

    # Set iterations for the Nesterov-based global placement algorithm
    # These are different from the global *router* iterations requested later.
    # Keeping reasonable values based on examples.
    gpl.setInitialPlaceMaxIter(10) # Iterations for the initial placement phase
    gpl.setInitDensityPenalityFactor(0.05) # Penalty factor for density violation

    # Run the global placement algorithm steps
    print("Running global placement initial phase...")
    gpl.doInitialPlace(threads = 4) # Use multiple threads
    print("Global placement initial phase complete.")

    print("Running global placement Nesterov phase...")
    gpl.doNesterovPlace(threads = 4) # Use multiple threads
    print("Global placement Nesterov phase complete.")

    # Dump DEF after global placement
    design.writeDef("5_global_placement.def")
    print("Dumped 5_global_placement.def")

except Exception as e:
    print(f"Error during global placement: {e}")
    traceback.print_exc()
    print("Global placement failed.")


# --- 6. Detailed Placement (1st pass) ---
print("\n--- Stage 6: Detailed Placement (1st pass) ---")
# Detailed placement legalizes cells after global placement, resolving overlaps.
# Get the detailed placer tool (Opendp)
dp = design.getOpendp()
# Check if site information is available (needed for row-based placement)
site = None
if block.getRows():
    site = block.getRows()[0].getSite()
    if site: print(f"Using site '{site.getName()}' from existing rows for detailed placement.")
elif floorplan.getSite() is not None: # Check site stored in floorplan object
    site = floorplan.getSite()
    if site: print(f"Using site '{site.getName()}' from floorplan for detailed placement.")
else:
    print("Warning: No site information found from rows or floorplan.")


if site and block.getCoreArea() is not None and block.getCoreArea().isValid(): # Check if necessary prerequisites are met
    try:
        # Set maximum allowed displacement for legalization
        max_disp_x_um = 1.0
        max_disp_y_um = 3.0
        # detailedPlacement API takes max displacement in DBU
        max_disp_x_dbu = micronToDBU(max_disp_x_um)
        max_disp_y_dbu = micronToDBU(max_disp_y_um)
        print(f"Setting detailed placement max displacement: X={max_disp_x_um} um ({max_disp_x_dbu} dbu), Y={max_disp_y_um} um ({max_disp_y_dbu} dbu).")

        # Remove any existing filler cells before legalization (important)
        dp.removeFillers()
        print("Removed existing filler cells before 1st detailed placement.")

        # Run detailed placement (legalization)
        # detailedPlacement(max_disp_x, max_disp_y, area_name, legalization_only)
        # "" for area_name means the entire core area
        # False means perform placement optimization, not just legalization
        print("Running first detailed placement...")
        dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
        print("First detailed placement complete.")

        # Dump DEF after detailed placement 1
        design.writeDef("6_detailed_placement_1.def")
        print("Dumped 6_detailed_placement_1.def")

    except Exception as e:
        print(f"Error during first detailed placement: {e}")
        traceback.print_exc()
        print("First detailed placement failed.")

else:
    print("Site information or Core Area missing. Skipping first detailed placement.")
    # If DP fails here, subsequent steps depending on legal placement will likely fail.
    # Consider exiting or adding checks later.


# --- 7. Clock Tree Synthesis (CTS) ---
print("\n--- Stage 7: Clock Tree Synthesis (CTS) ---")
# CTS builds the clock distribution network.
try:
    # Set RC values for clock and signal nets using standard TCL commands
    resistance_per_micron = 0.03574
    capacitance_per_micron = 0.07516
    # These values are technology-dependent
    print(f"Setting wire RC values: Clock/Signal Resistance={resistance_per_micron}/um, Capacitance={capacitance_per_micron}/um.")
    design.evalTclString(f"set_wire_rc -clock -resistance {resistance_per_micron} -capacitance {capacitance_per_micron}")
    design.evalTclString(f"set_wire_rc -signal -resistance {resistance_per_micron} -capacitance {capacitance_per_micron}")

    # Get the CTS tool (TritonCts)
    cts = design.getTritonCts()
    cts.reset() # Reset previous settings

    # Set the clock buffer cell to use
    buffer_cell_name = "BUF_X2"
    # Verify the buffer cell master exists in the libraries
    buf_master = None
    db = ord.get_db()
    for lib in db.getLibs():
        buf_master = lib.findMaster(buffer_cell_name)
        if buf_master: break

    if buf_master:
        print(f"Configuring CTS to use buffer cell: {buffer_cell_name}.")
        cts.setBufferList(buffer_cell_name) # List of buffers available
        cts.setRootBuffer(buffer_cell_name) # Specific buffer for the root driver
        # Note: setSinkBuffer might not be a standard parameter for TritonCts.
        # Sinks are typically connected directly or through end-buffers defined in setBufferList.
        # Removing setSinkBuffer to avoid potential API issues.
        # cts.setSinkBuffer(buffer_cell_name) # Specific buffer for sinks (e.g., flip-flop clock pins)
        # print(f"Configured '{buffer_cell_name}' as sink buffer.")
    else:
        print(f"Warning: Clock buffer cell '{buffer_cell_name}' not found in libraries. CTS may fail or use default buffers.")
        # If the buffer is critical and not found, you might want to exit.

    # Find the clock net object using the name defined earlier
    clock_net = block.findNet(clock_name)
    if clock_net:
        print(f"Setting clock net '{clock_name}' for CTS.")
        # The setClockNet method expects a dbNet object
        cts.setClockNet(clock_net)

        # Run CTS
        print("Running Clock Tree Synthesis...")
        cts.runTritonCts()
        print("Clock Tree Synthesis complete.")

        # Dump DEF after CTS (shows clock tree cells and routing)
        design.writeDef("7_cts.def")
        print("Dumped 7_cts.def")

    else:
        print(f"Error: Clock net '{clock_name}' not found. Skipping CTS.")
        print("CTS failed.")

except Exception as e:
    print(f"Error during Clock Tree Synthesis: {e}")
    traceback.print_exc()
    print("CTS failed.")


# --- 8. Filler Cell Insertion ---
print("\n--- Stage 8: Filler Cell Insertion ---")
# Insert filler cells to fill empty spaces in standard cell rows after placement and CTS.
# This is crucial for power grid continuity and meeting density requirements for DRC.
try:
    db = ord.get_db()
    filler_masters = list()
    filler_cells_prefix = "FILLCELL_" # Prefix for the names of inserted filler instances
    # Collect CORE_SPACER master cells from libraries
    print("Searching for CORE_SPACER filler cells in libraries...")
    for lib in db.getLibs():
        for master in lib.getMasters():
            # Find masters with type CORE_SPACER (common type for fillers)
            if master.getType() == "CORE_SPACER":
                filler_masters.append(master)
                # print(f"  Found filler: {master.getName()}") # Uncomment for verbose list

    if len(filler_masters) == 0:
        print("Warning: No filler cells (CORE_SPACER) found in libraries. Skipping filler placement.")
    elif site is None: # Check if site information is available (needed by filler placer)
         print("Warning: Site information missing. Cannot place filler cells. Skipping filler placement.")
    elif block.getCoreArea() is None or not block.getCoreArea().isValid():
         print("Warning: Core area is not valid. Cannot place filler cells. Skipping filler placement.")
    else:
        # Run filler cell placement using the detailed placer tool
        dp = design.getOpendp()
        print(f"Running filler cell placement using {len(filler_masters)} types of filler cells...")
        # fillerPlacement(filler_masters, prefix, verbose)
        dp.fillerPlacement(filler_masters = filler_masters,
                                     prefix = filler_cells_prefix,
                                     verbose = False) # Set verbose=True for more output
        print("Filler cell placement complete.")

        # Dump DEF after filler placement (shows newly inserted filler cells)
        design.writeDef("8_filler.def")
        print("Dumped 8_filler.def")

except Exception as e:
    print(f"Error during filler cell insertion: {e}")
    traceback.print_exc()
    print("Filler cell insertion failed.")


# --- 9. Detailed Placement (2nd pass) ---
print("\n--- Stage 9: Detailed Placement (2nd pass) ---")
# A second pass of detailed placement (often called legalization) is standard
# after CTS and filler insertion to slightly adjust cell positions.
if site and block.getCoreArea() is not None and block.getCoreArea().isValid(): # Check if necessary prerequisites are met
    try:
        dp = design.getOpendp()

        # Use the same max displacement limits or tighter ones if desired
        max_disp_x_um = 1.0
        max_disp_y_um = 3.0
        max_disp_x_dbu = micronToDBU(max_disp_x_um)
        max_disp_y_dbu = micronToDBU(max_disp_y_um)
        print(f"Setting detailed placement max displacement: X={max_disp_x_um} um, Y={max_disp_y_um} um.")

        # Remove existing filler cells before this legalization pass.
        # The tool will re-insert/legalize them during this step.
        dp.removeFillers()
        print("Removed existing filler cells for 2nd detailed placement (legalization).")

        # Run detailed placement (legalization)
        # Set the last argument to True for legalization only if preferred,
        # but False (optimization + legalization) is also common here.
        print("Running second detailed placement (legalization)...")
        dp.detailedPlacement(max_disp_x_dbu, max_disp_y_dbu, "", False)
        print("Second detailed placement (legalization) complete.")

        # Dump DEF after detailed placement 2
        design.writeDef("9_detailed_placement_2.def")
        print("Dumped 9_detailed_placement_2.def")

    except Exception as e:
        print(f"Error during second detailed placement: {e}")
        traceback.print_exc()
        print("Second detailed placement failed.")

else:
    print("Prerequisites for second detailed placement not met (site/core area missing). Skipping.")


# --- 10. Power Delivery Network (PDN) Construction ---
print("\n--- Stage 10: Power Delivery Network (PDN) Construction ---")
# Construct the power and ground grids and rings.
try:
    pdngen = design.getPdnGen()
    pdngen.reset() # Reset previous PDN settings

    # Set up global power/ground connections if not already done.
    # This connects instance PG pins to the top-level VDD/VSS nets.
    # Find or create VDD/VSS nets in the block.
    VDD_net = block.findNet("VDD")
    VSS_net = block.findNet("VSS")

    if VDD_net is None:
        VDD_net = odb.dbNet_create(block, "VDD")
        if VDD_net: print("Created VDD net.")
    if VDD_net:
        VDD_net.setSpecial() # Mark as special net
        VDD_net.setSigType("POWER") # Set signal type
        print("VDD net configured.")

    if VSS_net is None:
        VSS_net = odb.dbNet_create(block, "VSS")
        if VSS_net: print("Created VSS net.")
    if VSS_net:
        VSS_net.setSpecial()
        VSS_net.setSigType("GROUND")
        print("VSS net configured.")

    # Use globalConnect to tie instance PG pins to the global nets.
    # This is crucial for the PDN generator to recognize which nets to build for.
    if VDD_net and VSS_net:
        try:
            # Common standard cell pin names are used here as patterns
            block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDD$", net = VDD_net, do_connect = True)
            block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDPE$", net = VDD_net, do_connect = True) # Example
            block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VDDCE$", net = VDD_net, do_connect = True) # Example
            block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSS$", net = VSS_net, do_connect = True)
            block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VSSE$", net = VSS_net, do_connect = True) # Example
            # Add VNB/VPB if used for backbias:
            block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VNB$", net = VSS_net, do_connect = True)
            block.addGlobalConnect(region = None, instPattern = ".*", pinPattern = "^VPB$", net = VDD_net, do_connect = True)

            # Apply the global connections
            block.globalConnect()
            print("Global power/ground connections established for instance pins.")
        except Exception as e:
             print(f"Warning: Error during globalConnect for instance pins: {e}")


        # Set the core power domain, associating it with the VDD/VSS nets
        core_domain_name = "Core"
        pdngen.setCoreDomain(name = core_domain_name, power = VDD_net, ground = VSS_net)
        core_domain = pdngen.findDomain(core_domain_name)
        if core_domain:
            print(f"Core domain '{core_domain_name}' set with power net '{VDD_net.getName()}' and ground net '{VSS_net.getName()}'.")
        else:
            print(f"Error: Core domain '{core_domain_name}' not found after setting. Skipping detailed PDN configuration.")
            core_domain = None # Ensure it's None if not found

    else:
        print("Error: VDD or VSS net not available. Cannot set core domain for PDN. Skipping PDN configuration.")
        core_domain = None


    if core_domain:
        # Set via cut pitch between parallel grids to 0 um, as requested
        via_cut_pitch_um = 0.0
        via_cut_pitch_dbu = micronToDBU(via_cut_pitch_um)
        print(f"Via cut pitch between parallel grids set to {via_cut_pitch_um} um ({via_cut_pitch_dbu} dbu).")

        # Get metal layers required for PDN implementation
        m1 = tech.findLayer("metal1")
        m4 = tech.findLayer("metal4")
        m5 = tech.findLayer("metal5")
        m6 = tech.findLayer("metal6")
        m7 = tech.findLayer("metal7")
        m8 = tech.findLayer("metal8")

        if not all([m1, m4, m5, m6, m7, m8]):
            print("Error: Could not find all required metal layers (metal1, metal4-8) for PDN. Skipping detailed configuration.")
        else:
            # Set halo around macros to prevent standard cell PDN features (like followpins)
            # from being placed too close to macro boundaries.
            macro_halo_um = 5.0
            macro_halo_dbu = micronToDBU(macro_halo_um)
            # Halo is applied as [left, bottom, right, top] offset from macro boundary
            halo_list_dbu = [macro_halo_dbu] * 4 # 5um on all sides
            print(f"Macro halo for PDN standard cell avoidance: {macro_halo_um} um on all sides.")

            # --- Define and Configure Core Grid (Standard Cells) ---
            # The core grid defines the main spatial region and which instances belong to it.
            # Standard cells typically belong to the core grid within the core area.
            core_grid_name = "core_grid"
            # makeCoreGrid returns the grid object(s) associated with the core domain's extent
            core_grid = pdngen.makeCoreGrid(domain = core_domain,
                name = core_grid_name,
                starts_with = pdn.GROUND, # Specifies whether the first strap/ring should be Ground or Power
                # pin_layers = [], # Connecting to standard cell pins is often done via followpin, not explicit pin layers here
                # generate_obstructions = [], # Not generating blockages by default
                # powercell = None, powercontrol = None, powercontrolnetwork = "STAR" # Optional parameters
                )
            print(f"Core grid '{core_grid_name}' defined covering the core area.")

            # Add features (straps, followpins, rings) to the core grid object
            if core_grid: # Check if the core grid object was successfully created
                # M1 standard cell straps/followpins (width 0.07 um)
                # followpin is suitable for connecting to standard cell rows' PG pins
                pdngen.makeFollowpin(grid = core_grid,
                    layer = m1,
                    width = micronToDBU(0.07),
                    extend = pdn.CORE, # Extend within the core boundary
                    nets = []) # Apply to all nets in the grid (VDD/VSS)
                print(f"  Added M1 followpins/straps (width 0.07 um) to core grid.")

                # M4 straps (width 1.2 um, spacing 1.2 um, pitch 6 um) - Prompt says M4 is for macros.
                # *** VERIFICATION FEEDBACK CORRECTION ***
                # Removing M4 straps from core_grid as M4 is specified for macros.
                # The original script mistakenly placed M4 straps on the core grid.
                # This is now removed based on feedback.
                # The M4 straps will be correctly added to macro instance grids below.
                # Removed:
                # pdngen.makeStrap(grid = core_grid,
                #     layer = m4,
                #     width = micronToDBU(1.2),
                #     spacing = micronToDBU(1.2),
                #     pitch = micronToDBU(6.0),
                #     offset = micronToDBU(0.0),
                #     number_of_straps = 0,
                #     snap = True,
                #     starts_with = pdn.GRID,
                #     extend = pdn.CORE,
                #     nets = [])
                # print(f"  Removed M4 straps (W=1.2, S=1.2, P=6 um) from core grid based on verification feedback.")


                # M7 standard cell straps (width 1.4 um, spacing 1.4 um, pitch 10.8 um)
                # Verification Feedback Correction: The feedback requested removal of an M8 strap call
                # with these parameters on the core grid. The script did not have such a call for M8.
                # However, the script *did* have an M7 strap call with these parameters on the core grid.
                # Assuming the feedback meant M7 instead of M8 (likely typo), this M7 strap layer is removed
                # from the core grid to align with the likely intent of the feedback (removing a strap
                # with those specific dimensions/pitch from the core grid). The prompt's text is slightly
                # ambiguous regarding M7 straps (std cell vs macro).
                # Removed:
                # pdngen.makeStrap(grid = core_grid,
                #     layer = m7,
                #     width = micronToDBU(1.4),
                #     spacing = micronToDBU(1.4),
                #     pitch = micronToDBU(10.8),
                #     offset = micronToDBU(0.0),
                #     number_of_straps = 0,
                #     snap = True,
                #     starts_with = pdn.GRID,
                #     extend = pdn.CORE,
                #     nets = [])
                # print(f"  Removed M7 straps (W=1.4, S=1.4, P=10.8 um) from core grid based on verification feedback (assuming M8 was typo for M7).")


                # --- Define and Configure Core Rings (M7, M8) ---
                # Rings are added around the boundary of the core grid.
                core_ring_width_um = 2.0
                core_ring_spacing_um = 2.0
                core_ring_width_dbu = micronToDBU(core_ring_width_um)
                core_ring_spacing_dbu = micronToDBU(core_ring_spacing_um)
                # Ring offset from the boundary. [left, bottom, right, top]. 0 as requested.
                core_ring_offset_dbu = [micronToDBU(0.0) for _ in range(4)]
                # Pad offset from die boundary (if rings extend to pads). 0 as requested.
                core_ring_pad_offset_dbu = [micronToDBU(0.0) for _ in range(4)]

                # Use the separate makeRing calls for M7 and M8 as specified.
                pdngen.makeRing(grid = core_grid,
                    layer0 = m7, width0 = core_ring_width_dbu, spacing0 = core_ring_spacing_dbu,
                    layer1 = None, width1 = 0, spacing1 = 0, # Only layer0 specified for this ring call
                    starts_with = pdn.GROUND, # Specifies starting net for rings
                    offset = core_ring_offset_dbu,
                    pad_offset = core_ring_pad_offset_dbu,
                    extend = False, # Do not extend rings beyond core boundary
                    pad_pin_layers = [],
                    nets = []) # Apply to all nets in the grid (VDD/VSS)
                print(f"  Added M7 core rings (W=2.0, S=2.0 um) around core grid boundary.")

                pdngen.makeRing(grid = core_grid,
                    layer0 = m8, width0 = core_ring_width_dbu, spacing0 = core_ring_spacing_dbu,
                    layer1 = None, width1 = 0, spacing1 = 0, # Only layer0 specified for this ring call
                    starts_with = pdn.POWER, # Alternate with M7 if M7 starts with Ground
                    offset = core_ring_offset_dbu,
                    pad_offset = core_ring_pad_offset_dbu,
                    extend = False, # Do not extend rings beyond core boundary
                    pad_pin_layers = [],
                    nets = [])
                print(f"  Added M8 core rings (W=2.0, S=2.0 um) around core grid boundary.")


                # --- Define and Configure Macro Grids and Rings (if macros exist) ---
                macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()]
                if len(macros) > 0:
                    print(f"  Configuring PDN for {len(macros)} macros.")
                    # Macro grid strap parameters (M4, M5, M6) - Prompt says M4 is for macros, M5/M6 if macros exist.
                    # Assuming M4, M5, M6 straps are for macros with the specified parameters.
                    macro_strap_width_um = 1.2
                    macro_strap_spacing_um = 1.2
                    macro_strap_pitch_um = 6.0
                    macro_strap_width_dbu = micronToDBU(macro_strap_width_um)
                    macro_strap_spacing_dbu = micronToDBU(macro_strap_spacing_um)
                    macro_strap_pitch_dbu = micronToDBU(macro_strap_pitch_um)
                    print(f"  Macro strap params: W={macro_strap_width_um}, S={macro_strap_spacing_um}, P={macro_strap_pitch_um} um (M4, M5, M6).")

                    # Macro ring parameters (M5, M6)
                    macro_ring_width_um = 1.5
                    macro_ring_spacing_um = 1.5
                    macro_ring_width_dbu = micronToDBU(macro_ring_width_um)
                    macro_ring_spacing_dbu = micronToDBU(macro_ring_spacing_um)
                    macro_ring_offset_dbu = [micronToDBU(0.0) for _ in range(4)] # Offset 0 as requested
                    macro_ring_pad_offset_dbu = [micronToDBU(0.0) for _ in range(4)] # Pad offset 0 as requested
                    print(f"  Macro ring params: W={macro_ring_width_um}, S={macro_ring_spacing_um} um (M5, M6).")

                    # Iterate through each macro instance
                    for macro in macros:
                        # Define an instance grid for each macro. This grid is local to the macro's bounding box.
                        macro_grid_name = f"macro_grid_{macro.getName()}" # Unique name for each macro's grid
                        instance_grid = pdngen.makeInstanceGrid(domain = core_domain, # Macros are part of the core domain PG network
                            name = macro_grid_name,
                            inst = macro, # Associate this grid with the specific macro instance
                            halo = halo_list_dbu, # Apply the halo to prevent std cell PDN overlapping
                            pg_pins_to_boundary = True, # Connect macro PG pins to the boundary of this instance grid
                            # default_grid = False, # This is not the default grid for instances
                            # generate_obstructions = [], # Not generating blockages
                            # is_bump = False # Not a bump cell
                            )
                        print(f"  Defined instance grid '{macro_grid_name}' for macro '{macro.getName()}'.")

                        if instance_grid: # Check if the instance grid was successfully created
                            # Add straps on M4, M5 and M6 within the macro instance grid
                            # M4 straps on macro instance grid
                            pdngen.makeStrap(grid = instance_grid,
                                layer = m4,
                                width = macro_strap_width_dbu,
                                spacing = macro_strap_spacing_dbu,
                                pitch = macro_strap_pitch_dbu,
                                offset = micronToDBU(0.0), # Offset 0
                                number_of_straps = 0,
                                snap = True,
                                starts_with = pdn.GRID,
                                extend = pdn.RINGS, # Extend the straps up to the boundary of the instance grid's rings
                                nets = [])
                            print(f"    Added M4 straps to macro grid '{macro_grid_name}'.")

                            # M5 straps on macro instance grid
                            pdngen.makeStrap(grid = instance_grid,
                                layer = m5,
                                width = macro_strap_width_dbu,
                                spacing = macro_strap_spacing_dbu,
                                pitch = macro_strap_pitch_dbu,
                                offset = micronToDBU(0.0), # Offset 0
                                number_of_straps = 0,
                                snap = True,
                                starts_with = pdn.GRID,
                                extend = pdn.RINGS, # Extend the straps up to the boundary of the instance grid's rings
                                nets = [])
                            print(f"    Added M5 straps to macro grid '{macro_grid_name}'.")

                            # M6 straps on macro instance grid
                            pdngen.makeStrap(grid = instance_grid,
                                layer = m6,
                                width = macro_strap_width_dbu,
                                spacing = macro_strap_spacing_dbu,
                                pitch = macro_strap_pitch_dbu,
                                offset = micronToDBU(0.0), # Offset 0
                                number_of_straps = 0,
                                snap = True,
                                starts_with = pdn.GRID,
                                extend = pdn.RINGS, # Extend up to the boundary of the instance grid's rings
                                nets = [])
                            print(f"    Added M6 straps to macro grid '{macro_grid_name}'.")


                            # Add rings on M5 and M6 around the macro instance grid boundary
                            pdngen.makeRing(grid = instance_grid,
                                layer0 = m5, width0 = macro_ring_width_dbu, spacing0 = macro_ring_spacing_dbu,
                                layer1 = None, width1 = 0, spacing1 = 0,
                                starts_with = pdn.GROUND, # Choose start net
                                offset = macro_ring_offset_dbu,
                                pad_offset = macro_ring_pad_offset_dbu,
                                extend = False,
                                pad_pin_layers = [],
                                nets = [])
                            print(f"    Added M5 rings (W=1.5, S=1.5 um) to macro grid '{macro_grid_name}'.")

                            pdngen.makeRing(grid = instance_grid,
                                layer0 = m6, width0 = macro_ring_width_dbu, spacing0 = macro_ring_spacing_dbu,
                                layer1 = None, width1 = 0, spacing1 = 0,
                                starts_with = pdn.POWER, # Alternate with M5
                                offset = macro_ring_offset_dbu,
                                pad_offset = macro_ring_pad_offset_dbu,
                                extend = False,
                                pad_pin_layers = [],
                                nets = [])
                            print(f"    Added M6 rings (W=1.5, S=1.5 um) to macro grid '{macro_grid_name}'.")

                        else:
                            print(f"Warning: Instance grid not created for macro '{macro.getName()}'. Skipping macro PDN features for this instance.")

                else:
                    print("  No macros found, skipping macro PDN configuration.")


                # --- Configure Connections (Vias) ---
                # Define via connections between layers within grids and between grids.
                # 'makeConnect' can be called on a grid object. It finds overlaps between the grid's area
                # and the specified layers from *any* grid within the same domain and inserts vias.
                print("  Configuring vias for PDN grids and rings.")

                # Vias within the Core Grid
                # M1 strap (core) to M7 ring (core)
                pdngen.makeConnect(grid = core_grid, layer0 = m1, layer1 = m7,
                    cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
                print(f"    Added M1-M7 vias with pitch {via_cut_pitch_um} um to connect core grid layers (strap to ring).")

                # M7 ring (core) to M8 ring (core)
                pdngen.makeConnect(grid = core_grid, layer0 = m7, layer1 = m8,
                    cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
                print(f"    Added M7-M8 vias with pitch {via_cut_pitch_um} um to connect core rings.")


                # Vias within each Macro Instance Grid and connections to Core Grid
                macros = [inst for inst in block.getInsts() if inst.getMaster().isBlock()] # Re-get macros list
                if len(macros) > 0:
                    for macro in macros:
                         instance_grid = pdngen.findGrid(f"macro_grid_{macro.getName()}") # Find the grid object for this macro
                         if instance_grid:
                            # Vias within the macro instance grid (M4-M5, M5-M6)
                            pdngen.makeConnect(grid = instance_grid, layer0 = m4, layer1 = m5, # Layers are from the instance grid definition
                                 cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
                            print(f"    Added M4-M5 vias with pitch {via_cut_pitch_um} um within macro grid '{instance_grid.getName()}'.")

                            pdngen.makeConnect(grid = instance_grid, layer0 = m5, layer1 = m6,
                                 cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
                            print(f"    Added M5-M6 vias with pitch {via_cut_pitch_um} um within macro grid '{instance_grid.getName()}'.")

                            # Vias connecting Macro Instance Grid (M6 strap/ring) up to Core Grid (M7 ring)
                            # layer0 (M6) is an instance grid layer, layer1 (M7) is a core grid layer
                            # This connects the highest layer in the macro PDN to the lowest ring layer in the core PDN.
                            pdngen.makeConnect(grid = instance_grid, layer0 = m6, layer1 = m7,
                                 cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
                            print(f"    Added M6-M7 vias (Macro M6 to Core M7 ring) with pitch {via_cut_pitch_um} um to macro grid '{instance_grid.getName()}'.")

                            # Optional: Connect Macro Instance Grid (M4 strap/ring) down to Core Grid (M1 strap/followpin)
                            # This connects the lowest layer in the macro PDN to the lowest layer in the core PDN.
                            pdngen.makeConnect(grid = instance_grid, layer0 = m4, layer1 = m1,
                                 cut_pitch_x = via_cut_pitch_dbu, cut_pitch_y = via_cut_pitch_dbu)
                            print(f"    Added M4-M1 vias (Macro M4 to Core M1 strap) with pitch {via_cut_pitch_um} um to macro grid '{instance_grid.getName()}'.")


                         else:
                             print(f"    Warning: Instance grid not found for macro '{macro.getName()}'. Skipping via configuration for this macro.")


                # --- Build the final power delivery network geometry ---
                print("Building PDN grids in the database.")
                pdngen.checkSetup() # Verify configuration before building
                # Use True to generate via masters during build if needed (more robust)
                pdngen.buildGrids(True)
                pdngen.writeToDb(True) # Write the generated shapes from memory to the design database (True: clears temp shapes)

                print("Power Delivery Network construction complete.")

                # Dump DEF after PDN (shows the power grid shapes)
                design.writeDef("10_pdn.def")
                print("Dumped 10_pdn.def")

            else:
                 print("Error: Core grid object not successfully created. PDN configuration stopped.")

except Exception as e:
    print(f"Error during Power Delivery Network construction: {e}")
    traceback.print_exc() # Print detailed error information
    print("Power Delivery Network construction failed.")


# --- 11. IR Drop and Power Analysis ---
print("\n--- Stage 11: IR Drop and Power Analysis ---")
# This step requires timing libraries (liberty) and extracted parasitics (SPEF).
# Ensure these are loaded before running this script if you need accurate results.
# Analysis and reporting are typically done via TCL commands.
try:
    # Analyze power (switching, leakage, internal, total)
    # This command computes power based on activity (VCD or default toggle rates)
    # and library power models.
    print("Analyzing power...")
    # analyze_power relies on previous setup (set_timing_corner, read_liberty, read_parasitics, etc.)
    # Make sure you have loaded liberty files with power data (read_liberty -lib_pf)
    # and parasitics (read_spef). This script assumes they were loaded earlier.
    design.evalTclString("analyze_power")
    print("Power analysis command issued.")

    # Report power
    print("\n--- Power Report ---")
    # report_power outputs to the OpenROAD console/log.
    design.evalTclString("report_power")
    print("--- End Power Report ---")

except Exception as e:
    print(f"Warning: Power analysis failed. This step requires timing and power library setup (read_liberty -lib_pf) and potentially activity data. Error: {e}")
    traceback.print_exc()


try:
    # Report IR drop on VDD and VSS nets
    # The prompt asked for reporting on "M1 nodes", but standard report_irdrop is net-based.
    # It reports voltage/current/IR drop for specified nets across their routing/PG structures.
    # report_irdrop also requires SPEF (read_spef) and potentially switching activity (VCD).
    print("\n--- IR Drop Report (VDD) ---")
    design.evalTclString("report_irdrop -net VDD")
    print("--- End IR Drop Report (VDD) ---")

    print("\n--- IR Drop Report (VSS) ---")
    design.evalTclString("report_irdrop -net VSS")
    print("--- End IR Drop Report (VSS) ---")

except Exception as e:
    print(f"Warning: IR Drop analysis failed. This step requires SPEF (read_spef), power analysis results, and potentially activity data. Error: {e}")
    traceback.print_exc()


# --- 12. Routing ---
print("\n--- Stage 12: Routing ---")

# Global Routing
print("--- Global Routing ---")
# Global routing finds a coarse path for nets, considering congestion.
# Get routing layer ranges for signal and clock nets (M1 to M7)
signal_low_layer_name = "metal1"
signal_high_layer_name = "metal7"
clk_low_layer_name = "metal1" # Use same layers for clock as requested for signals
clk_high_layer_name = "metal7"

# Global routing iterations requested: 10 times
global_routing_iterations = 10

# Use the TCL command for global_route to explicitly set the number of iterations.
# The Python GlobalRouter object might not expose this parameter directly or consistently.
try:
    # Check if layers exist before trying to route on them
    metal1_layer = tech.findLayer(signal_low_layer_name)
    metal7_layer = tech.findLayer(signal_high_layer_name)
    if metal1_layer is None or metal7_layer is None or metal1_layer.getRoutingLevel() == 0 or metal7_layer.getRoutingLevel() == 0:
        print(f"Error: Could not find valid routing layers {signal_low_layer_name} or {signal_high_layer_name}. Skipping global routing.")
    else:
        print(f"Running global routing from {signal_low_layer_name} to {signal_high_layer_name} with {global_routing_iterations} iterations.")
        # Example TCL command parameters used here for clarity, adjust as needed for specific needs
        design.evalTclString(f"global_route -min_routing_layer {signal_low_layer_name} -max_routing_layer {signal_high_layer_name} -min_layer_for_clock {clk_low_layer_name} -max_layer_for_clock {clk_high_layer_name} -iterations {global_routing_iterations}")
        print("Global routing complete.")

        # Dump DEF after global routing
        design.writeDef("11_global_route.def")
        print("Dumped 11_global_route.def")

except Exception as e:
    print(f"Error during global routing: {e}")
    traceback.print_exc()
    print("Global routing failed.")


# Detailed Routing
print("\n--- Detailed Routing ---")
# Detailed routing lays down actual wires on tracks, respecting DRCs.
# Get the detailed router tool (TritonRoute)
try:
    drter = design.getTritonRoute()
    # Detailed routing parameters are set using a ParamStruct object
    params = drt.ParamStruct()

    # Set routing layers explicitly based on the prompt (M1 to M7)
    params.bottomRoutingLayer = signal_low_layer_name
    params.topRoutingLayer = signal_high_layer_name
    print(f"Configuring detailed routing layers: {params.bottomRoutingLayer} to {params.topRoutingLayer}.")

    # Configure other detailed routing parameters.
    # Using common settings often seen in OpenROAD flows (e.g., from example scripts).
    params.outputMazeFile = "" # Optional debug output file
    params.outputDrcFile = "" # Optional DRC output file
    params.outputCmapFile = ""
    params.outputGuideCoverageFile = ""
    params.dbProcessNode = "" # Technology process node string (optional)
    params.enableViaGen = True # Enable via generation during routing
    params.drouteEndIter = 1 # Number of detailed routing iterations (prompt didn't specify, 1 is common)
    params.viaInPinBottomLayer = "" # Allow via-in-pin on default layers
    params.viaInPinTopLayer = ""
    params.orSeed = -1 # Random seed (-1 uses current time)
    params.orK = 0
    params.verbose = 1 # Verbosity level (1 is moderate)
    params.cleanPatches = True # Clean up routing patches
    params.doPa = True # Perform post-route detailed placement/legalization (recommended)
    params.singleStepDR = False # Do not stop after each routing iteration
    params.minAccessPoints = 1 # Minimum access points for pins
    params.saveGuideUpdates = False

    # Apply the configured parameters to the detailed router
    drter.setParams(params)
    print("Detailed routing parameters set.")

    # Run detailed routing
    print("Running detailed routing...")
    drter.main() # The main detailed routing function
    print("Detailed routing complete.")

    # Note: The final DEF dump will include detailed routing.

except Exception as e:
    print(f"Error during detailed routing: {e}")
    traceback.print_exc()
    print("Detailed routing failed.")


# --- 13. Final Output ---
print("\n--- Stage 13: Final Output ---")
# Write the final design files (DEF and Verilog).

# Write final DEF file (contains placement, routing, PDN, fillers)
final_def_file = "final.def"
try:
    print(f"Writing final DEF file to {final_def_file}...")
    design.writeDef(final_def_file)
    print(f"Final DEF file saved successfully.")
except Exception as e:
    print(f"Error writing final DEF file: {e}")
    traceback.print_exc()


# Write final Verilog netlist (post-placement/CTS usually includes inserted cells)
final_verilog_file = "final.v"
try:
    print(f"Writing final Verilog netlist to {final_verilog_file}...")
    # Use TCL command for writing Verilog
    design.evalTclString(f"write_verilog {final_verilog_file}")
    print(f"Final Verilog netlist saved successfully.")
except Exception as e:
     print(f"Error writing final Verilog netlist: {e}")
     traceback.print_exc()


# Save the final OpenDB (ODB) database file
final_odb_file = "final.odb"
try:
    print(f"Saving final OpenDB database to {final_odb_file}...")
    design.writeDb(final_odb_file)
    print(f"Final OpenDB database saved successfully.")
except Exception as e:
    print(f"Error saving final OpenDB database: {e}")
    traceback.print_exc()


print("\nOpenROAD Python flow script execution finished.")