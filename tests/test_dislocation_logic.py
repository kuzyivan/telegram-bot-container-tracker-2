import unittest
from datetime import datetime
from services.dislocation.trip_logic import is_trip_completed, is_new_trip, should_update_tracking

class TestDislocationTripLogic(unittest.TestCase):
    def test_is_trip_completed(self):
        # Позитивный случай
        self.assertTrue(is_trip_completed("Владивосток", "Владивосток", "Выгрузка"))
        self.assertTrue(is_trip_completed("Владивосток", "Владивосток", "раскредитование"))
        
        # Разные станции
        self.assertFalse(is_trip_completed("Хабаровск", "Владивосток", "Выгрузка"))
        
        # Другая операция
        self.assertFalse(is_trip_completed("Владивосток", "Владивосток", "Следование"))

    def test_is_new_trip(self):
        date1 = datetime(2025, 1, 1)
        date2 = datetime(2025, 1, 2)
        
        # Смена накладной
        self.assertTrue(is_new_trip("WB1", "WB2", "ST1", "ST1", date1, date1))
        
        # Смена станции назначения
        self.assertTrue(is_new_trip("WB1", "WB1", "ST1", "ST2", date1, date1))
        
        # Новая дата начала
        self.assertTrue(is_new_trip("WB1", "WB1", "ST1", "ST1", date1, date2))
        
        # Тот же рейс
        self.assertFalse(is_new_trip("WB1", "WB1", "ST1", "ST1", date1, date1))

    def test_should_update_tracking_not_completed(self):
        # Рейс не завершен, дата новее -> True
        existing_date = datetime(2025, 1, 1, 10, 0)
        new_date = datetime(2025, 1, 1, 12, 0)
        row_data = {'operation_date': new_date}
        
        self.assertTrue(should_update_tracking(
            existing_date, "Station A", "Station B", "Op A", "WB1", datetime(2025, 1, 1),
            row_data
        ))

    def test_should_update_tracking_completed_same_trip(self):
        # Рейс завершен, пришла инфа по тому же рейсу (старая или хвост) -> False
        finish_date = datetime(2025, 1, 1, 10, 0)
        row_data = {
            'operation_date': datetime(2025, 1, 1, 11, 0),
            'waybill': 'WB1',
            'to_station': 'Station B',
            'trip_start_datetime': datetime(2025, 1, 1)
        }
        
        # В БД он уже выгружен на Station B
        self.assertFalse(should_update_tracking(
            finish_date, "Station B", "Station B", "Выгрузка", "WB1", datetime(2025, 1, 1),
            row_data
        ))

    def test_should_update_tracking_completed_new_trip(self):
        # Рейс завершен, но пришла инфа о НОВОМ рейсе -> True
        finish_date = datetime(2025, 1, 1, 10, 0)
        row_data = {
            'operation_date': datetime(2025, 1, 2, 10, 0),
            'waybill': 'WB2', # Новая накладная
            'to_station': 'Station C',
            'trip_start_datetime': datetime(2025, 1, 2)
        }
        
        self.assertTrue(should_update_tracking(
            finish_date, "Station B", "Station B", "Выгрузка", "WB1", datetime(2025, 1, 1),
            row_data
        ))

if __name__ == '__main__':
    unittest.main()
