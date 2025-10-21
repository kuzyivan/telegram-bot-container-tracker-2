# zdtarif_bot/rail_calculator.py
import os
import logging
from core.data_loader import DataLoader
from core.calculator import Calculator

# --- Basic Logging Setup (adjust as needed) ---
# It's good practice to set up logging here in case this module is run independently
# or if the main bot's logging isn't configured early enough.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__) # Use standard Python logger

# --- Global Calculator Initialization ---
data_loader = None
calculator = None

try:
    # Get the absolute path to the directory where THIS file (rail_calculator.py) is located
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Construct the absolute path to the 'data' directory (assuming it's next to this file)
    data_dir_path = os.path.join(current_dir, 'data')
    
    logger.info(f"Initializing DataLoader with data path: {data_dir_path}")

    # Pass the absolute path to the DataLoader
    data_loader = DataLoader(data_dir_path) 
    calculator = Calculator(data_loader)
    
    logger.info("✅ DataLoader and Calculator initialized successfully in rail_calculator.")

except FileNotFoundError as e:
    logger.error(f"💥 CRITICAL: Data directory or file not found during initialization: {e}", exc_info=True)
    logger.error(f"   Attempted data directory path: {data_dir_path}")
    # Set calculator to None to prevent usage
    calculator = None 
    # Optionally re-raise if you want the main bot import to fail hard
    # raise 
except Exception as e:
    logger.error(f"💥 CRITICAL: Failed to initialize DataLoader or Calculator: {e}", exc_info=True)
    calculator = None
    # Optionally re-raise
    # raise

# --- Main Function for External Use ---
def get_distance_sync(station_code_1: str, station_code_2: str) -> int | None:
    """
    Calculates the tariff distance using the initialized calculator.
    Returns distance in km or None if not found or on error.
    
    This is the function intended to be imported by other services.
    """
    if not calculator: # Check if initialization failed
        logger.error("❌ Calculator not initialized, cannot calculate distance.")
        return None
        
    if not station_code_1 or not station_code_2:
        logger.warning("Received empty station code(s). Cannot calculate.")
        return None

    try:
        # Assuming calculator.get_distance handles internal errors and returns None if needed
        distance = calculator.get_distance(str(station_code_1), str(station_code_2))
        
        # Ensure the calculator returns None or a number > 0
        if distance is not None:
            distance_int = int(distance)
            if distance_int > 0:
                logger.debug(f"Distance calculated: {station_code_1} -> {station_code_2} = {distance_int} km")
                return distance_int
            else:
                # Handle cases where calculator might return 0 if stations are the same or adjacent with 0 distance
                logger.info(f"Calculator returned 0 or negative distance for {station_code_1} -> {station_code_2}.")
                return None # Treat 0 as 'not found' unless 0 is a valid tariff distance
        else:
            logger.info(f"Distance not found by calculator for {station_code_1} -> {station_code_2}.")
            return None
            
    except Exception as e:
        logger.error(f"❌ Unexpected error during distance calculation for {station_code_1}-{station_code_2}: {e}", exc_info=True)
        return None

# --- Example Usage (Optional - for testing this file directly) ---
if __name__ == '__main__':
    # This block runs only if you execute `python zdtarif_bot/rail_calculator.py`
    if calculator:
        logger.info("Running test calculations...")
        # Replace with actual codes for testing
        code1 = "181102" # Example: Селятино
        code2 = "850007" # Example: Инская
        
        dist = get_distance_sync(code1, code2)
        if dist:
            logger.info(f"Test: Distance between {code1} and {code2} = {dist} km")
        else:
            logger.warning(f"Test: Distance between {code1} and {code2} could not be calculated.")
            
        # Test non-existent route
        code3 = "999999" 
        dist_none = get_distance_sync(code1, code3)
        if not dist_none:
            logger.info(f"Test: Correctly handled non-existent route {code1} -> {code3}.")
        else:
             logger.error(f"Test FAILED: Expected None for non-existent route {code1} -> {code3}, got {dist_none}.")
             
    else:
        logger.error("Cannot run tests because Calculator failed to initialize.")