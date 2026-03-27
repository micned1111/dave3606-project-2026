import unittest
from unittest.mock import Mock, patch, mock_open, MagicMock
import json

# Import the functions we want to test
from server import render_sets_page, get_set_json, load_set_data


class MockDatabase:
    def __init__(self):
        self.queries = []
        self.close_called = False
    
    def execute_and_fetch_all(self, query, params=()):
        self.queries.append((query, params))
        
        # Return mock data based on query pattern
        if "select id, name from lego_set" in query.lower():
            return [
                ("00-1", "LEGO Classic Bricks"),
                ("10-2", "LEGO City Police"),
            ]
        elif "SELECT name FROM lego_set WHERE id" in query:
            return [("LEGO Classic Bricks",)]
        elif "SELECT brick_type_id, color_id, count FROM lego_inventory" in query:
            return [
                ("brick-001", 1, 5),
                ("brick-002", 4, 3),
            ]
        elif "SELECT name, preview_image_url FROM lego_brick" in query:
            # Return different data based on brick_type_id
            if "brick-001" in str(params):
                return [("Red Brick", "https://example.com/red.jpg")]
            elif "brick-002" in str(params):
                return [("Blue Brick", "https://example.com/blue.jpg")]
        
        return []
    
    def close(self):
        self.close_called = True


class TestRenderSetsPage(unittest.TestCase):
    @patch("server.open", new_callable=mock_open, read_data="<html>{METATAG}<body>{ROWS}</body></html>")
    def test_render_sets_page_utf8(self, mock_file):
        db = MockDatabase()
        result = render_sets_page(db, "utf-8")
        
        # Check that the database query was correct
        self.assertEqual(len(db.queries), 1)
        query, _ = db.queries[0]
        self.assertIn("select id, name from lego_set", query.lower())
        
        # Check that the result contains expected HTML elements
        self.assertIn('<meta charset="UTF-8">', result)
        self.assertIn('href="/set?id=00-1"', result)
        self.assertIn('LEGO Classic Bricks', result)
        self.assertIn('LEGO City Police', result)
        self.assertIn('<a href="/set?id=10-2">10-2</a>', result)
    
    @patch("server.open", new_callable=mock_open, read_data="<html>{METATAG}<body>{ROWS}</body></html>")
    def test_render_sets_page_utf16(self, mock_file):
        db = MockDatabase()
        result = render_sets_page(db, "utf-16")
        
        # Check that UTF-16 was NOT added to meta tag
        self.assertNotIn('<meta charset="UTF-16">', result)
        self.assertNotIn('charset', result)
        # But the data should still be present
        self.assertIn('LEGO Classic Bricks', result)
    
    @patch("server.open", new_callable=mock_open, read_data="<html>{METATAG}<body>{ROWS}</body></html>")
    def test_render_sets_page_default_encoding(self, mock_file):
        db = MockDatabase()
        result = render_sets_page(db, None)
        
        # Should default to UTF-8
        self.assertIn('<meta charset="UTF-8">', result)
    
    @patch("server.open", new_callable=mock_open, read_data="<html>{METATAG}<body>{ROWS}</body></html>")
    def test_render_sets_page_invalid_encoding(self, mock_file):
        db = MockDatabase()
        result = render_sets_page(db, "iso-8859-1") # unrecognized encoding
        
        # Should default to UTF-8 for invalid encoding
        self.assertIn('<meta charset="UTF-8">', result)


class TestGetSetJson(unittest.TestCase):    
    def test_get_set_json_structure(self):
        db = MockDatabase()
        result = get_set_json(db, "00-1")
        
        data = json.loads(result)
        
        self.assertEqual(data["set_id"], "00-1")
        self.assertEqual(data["set_name"], "LEGO Classic Bricks")
        self.assertIsInstance(data["bricks_data"], list)
        self.assertEqual(len(data["bricks_data"]), 2)
    
    def test_get_set_json_brick_data(self):
        db = MockDatabase()
        
        result = get_set_json(db, "00-1")
        data = json.loads(result)
        
        # Check first brick
        first_brick = data["bricks_data"][0]
        self.assertIn("img_url", first_brick)
        self.assertIn("name", first_brick)
        self.assertIn("color", first_brick)
        self.assertIn("count", first_brick)
    
    def test_get_set_json_valid_json(self):
        db = MockDatabase()
        result = get_set_json(db, "00-1")
        
        # Should not raise an exception
        try:
            json.loads(result)
        except json.JSONDecodeError:
            self.fail("get_set_json did not return valid JSON")


class TestLoadSetData(unittest.TestCase):    
    def test_load_set_data_queries(self):
        db = MockDatabase()
        load_set_data(db, "00-1")
        
        # Should make 3 types of queries: set name, inventory, brick details
        self.assertGreaterEqual(len(db.queries), 3)
        
        # Check first query is for set name
        query, params = db.queries[0]
        self.assertIn("SELECT name FROM lego_set", query)
        self.assertIn("00-1", params)
    
    def test_load_set_data_returns_tuples(self):
        db = MockDatabase()
        name, bricks = load_set_data(db, "00-1")
        
        self.assertIsInstance(name, str)
        self.assertEqual(name, "LEGO Classic Bricks")
        self.assertIsInstance(bricks, list)
    
    def test_load_set_data_brick_structure(self):
        db = MockDatabase()
        name, bricks = load_set_data(db, "00-1")
        
        # Check each brick has required fields
        for brick in bricks:
            self.assertIn("img_url", brick)
            self.assertIn("name", brick)
            self.assertIn("color", brick)
            self.assertIn("count", brick)
    
    def test_load_set_data_brick_count(self):
        db = MockDatabase()
        name, bricks = load_set_data(db, "00-1")
        
        # MockDatabase returns 2 inventory items
        self.assertEqual(len(bricks), 2)
    
    def test_load_set_data_html_escaping(self):
        # Create a custom mock that returns HTML characters
        class MockDatabaseWithHTML(MockDatabase):
            def execute_and_fetch_all(self, query, params=()):
                self.queries.append((query, params))
                
                if "select id, name from lego_set" in query.lower():
                    return [("test-id", "Test Set")]
                elif "SELECT name FROM lego_set WHERE id" in query:
                    return [("Test Set",)]
                elif "SELECT brick_type_id, color_id, count FROM lego_inventory" in query:
                    return [("brick-001", 1, 5)]
                elif "SELECT name, preview_image_url FROM lego_brick" in query:
                    # Return data with HTML special characters
                    return [("Brick <script>alert()</script>", "https://example.com/brick.jpg")]
                return []
        
        db = MockDatabaseWithHTML()
        name, bricks = load_set_data(db, "test-id")
        
        if bricks:
            # Check that < and > are escaped in output
            self.assertIn("&lt;", bricks[0]["name"])
            self.assertIn("&gt;", bricks[0]["name"])


class TestDatabaseQueryAccuracy(unittest.TestCase):    
    def test_render_sets_exact_query(self):
        db = MockDatabase()
        render_sets_page(db, "utf-8")
        
        query, params = db.queries[0]
        self.assertIn("select id, name from lego_set order by id", query.lower())
    
    def test_load_set_data_exact_queries(self):
        db = MockDatabase()
        load_set_data(db, "test-id")
        
        # Checking that all expected queries were made
        query_texts = [q[0] for q in db.queries]
        
        # Should have query for set name
        self.assertTrue(any("SELECT name FROM lego_set" in q for q in query_texts))
        
        # Should have query for inventory
        self.assertTrue(any("lego_inventory" in q for q in query_texts))
        
        # Should have query for brick details
        self.assertTrue(any("lego_brick" in q for q in query_texts))
    
    def test_load_set_specific_id_passed(self):
        db = MockDatabase()
        test_id = "custom-set-12345"
        
        load_set_data(db, test_id)
        
        # First query should have the set_id as a parameter
        query, params = db.queries[0]
        self.assertIn(test_id, params)


class TestDatabaseClass(unittest.TestCase):    
    @patch("server.psycopg.connect")
    def test_database_close_called(self, mock_connect):
        from server import Database
        
        # Create mock cursor and connection
        mock_cursor = Mock()
        mock_connection = Mock()
        mock_connect.return_value = mock_connection
        mock_connection.cursor.return_value = mock_cursor
        
        db = Database({})
        db.execute_and_fetch_all("SELECT 1")
        db.close()
        
        # Verify close was called on both
        mock_cursor.close.assert_called_once()
        mock_connection.close.assert_called_once()
    
    @patch("server.psycopg.connect")
    def test_database_execute_and_fetch_all(self, mock_connect):
        from server import Database
        
        mock_cursor = Mock()
        mock_connection = Mock()
        mock_connect.return_value = mock_connection
        mock_connection.cursor.return_value = mock_cursor
        
        # Mocking fetchall to return some data
        test_data = [("id1", "name1"), ("id2", "name2")]
        mock_cursor.fetchall.return_value = test_data
        
        db = Database({"host": "localhost"})
        result = db.execute_and_fetch_all("SELECT id, name FROM test_table")
        
        # Here I verify execute was called with the query
        mock_cursor.execute.assert_called_once_with("SELECT id, name FROM test_table", ())
        
        # Verifying that I got the fetchall result
        self.assertEqual(result, test_data)


if __name__ == "__main__":
    unittest.main()
